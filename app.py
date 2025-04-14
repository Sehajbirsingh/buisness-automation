import os
import pickle
from flask import Flask, request, jsonify, redirect, session, url_for, render_template, flash
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import google.generativeai as genai
from dotenv import load_dotenv
import logging

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO)

# --- Load Environment Variables ---
load_dotenv() # Load .env file if it exists (optional)

# --- Flask App Initialization ---
app = Flask(__name__)
# Use a persistent secret key in production, maybe from env vars
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

# --- Constants ---
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar'
]
# Ensure these files exist or guide the user
CLIENT_SECRETS_FILE = 'client_secret.json'
TOKEN_FILE = 'token.pkl'
# Make sure this matches Google Cloud Console Redirect URI for Web Application
REDIRECT_URI = 'http://localhost:5000/oauth2callback'

# --- Helper Functions ---

def credentials_to_dict(credentials):
    """Helper to convert Credentials object to a serializable dict for session."""
    return {'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes}

def get_credentials_from_session():
    """Retrieves Google credentials from session and refreshes if necessary."""
    creds_dict = session.get('google_credentials')
    if not creds_dict:
        logging.info("No Google credentials found in session.")
        return None

    try:
        credentials = Credentials(**creds_dict)
        if credentials and credentials.expired and credentials.refresh_token:
            logging.info("Google token expired, attempting refresh...")
            try:
                credentials.refresh(Request())
                session['google_credentials'] = credentials_to_dict(credentials)
                logging.info("Token refreshed successfully.")
                # Optionally re-save the refreshed token
                # with open(TOKEN_FILE, 'wb') as token_file:
                #     pickle.dump(credentials, token_file)
            except Exception as e:
                logging.error(f"Error refreshing token: {e}")
                # Clear potentially invalid credentials
                session.pop('google_credentials', None)
                session.pop('oauth_state', None)
                flash("Failed to refresh Google token. Please authenticate again.", "error")
                return None # Indicate failure
        return credentials
    except Exception as e:
        logging.error(f"Error loading credentials from session dict: {e}")
        return None


def get_google_flow():
    """Initializes the Google OAuth Flow."""
    if not os.path.exists(CLIENT_SECRETS_FILE):
        logging.error(f"{CLIENT_SECRETS_FILE} not found.")
        flash(f"Error: {CLIENT_SECRETS_FILE} not found. Please place it in the application directory.", "error")
        return None
    try:
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        return flow
    except Exception as e:
        logging.error(f"Error creating Google OAuth flow from {CLIENT_SECRETS_FILE}: {e}")
        flash(f"Error reading {CLIENT_SECRETS_FILE}. Check its format.", "error")
        return None

def fetch_recent_emails(service, max_results=3):
    """Fetches recent emails (Subject and Snippet)."""
    summaries = []
    try:
        # Try fetching unread first
        response = service.users().messages().list(userId='me', maxResults=max_results, q="is:unread").execute()
        messages = response.get('messages', [])

        # If no unread, fetch latest overall
        if not messages:
             logging.info("No unread messages found, fetching latest overall.")
             response = service.users().messages().list(userId='me', maxResults=max_results).execute()
             messages = response.get('messages', [])

        logging.info(f"Found {len(messages)} email messages.")
        for msg in messages:
            # Fetch only metadata to be faster and use less quota
            msg_data = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject']).execute()
            subject = next((h['value'] for h in msg_data.get('payload', {}).get('headers', []) if h['name'] == 'Subject'), '(No Subject)')
            snippet = msg_data.get('snippet', '')
            summaries.append(f"Subject: {subject}\nSnippet: {snippet}")
        return summaries
    except Exception as e:
        logging.error(f"Error fetching emails: {e}")
        flash(f"Error fetching emails: {e}", "error")
        # Handle potential API errors (e.g., permissions) gracefully
        raise # Re-raise to be caught by the calling route

# --- Flask Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Main page: Handles status checks, API key input, and displays features."""
    gemini_configured = 'gemini_api_key' in session
    google_authenticated = get_credentials_from_session() is not None

    # Handle API Key POST request
    if request.method == 'POST':
        api_key = request.form.get('gemini_api_key')
        if api_key:
            try:
                # Test the key immediately
                genai.configure(api_key=api_key)
                genai.list_models() # Simple test call
                session['gemini_api_key'] = api_key
                gemini_configured = True
                flash("Gemini API Key configured successfully!", "success")
                logging.info("Gemini API Key configured.")
            except Exception as e:
                logging.error(f"Error configuring Gemini with provided key: {e}")
                flash(f"Invalid Gemini API Key: {e}", "error")
                session.pop('gemini_api_key', None) # Remove invalid key
                gemini_configured = False
            # Redirect to GET to avoid form resubmission on refresh
            return redirect(url_for('index'))

    # Check for OAuth messages from redirect
    oauth_error = request.args.get('oauth_error')
    if oauth_error:
        flash(f"Google Authentication Failed: {oauth_error}", "error")

    oauth_success = request.args.get('oauth_success')
    if oauth_success:
         flash("Google Authentication Successful!", "success")

    return render_template('index.html',
                           gemini_configured=gemini_configured,
                           google_authenticated=google_authenticated)

@app.route('/authorize_google')
def authorize_google():
    """Starts the Google OAuth flow."""
    if not get_credentials_from_session(): # Only auth if not already authed
        flow = get_google_flow()
        if not flow:
            # Error flashed in get_google_flow()
            return redirect(url_for('index'))

        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent' # Force consent screen for refresh token
        )
        session['oauth_state'] = state
        logging.info(f"Redirecting user to Google Auth URL. State: {state}")
        return redirect(authorization_url)
    else:
        flash("Already authenticated with Google.", "info")
        return redirect(url_for('index'))


@app.route('/oauth2callback')
def oauth2callback():
    """Handles the redirect from Google after authorization."""
    state = session.get('oauth_state')
    logging.info(f"OAuth callback received. State from session: {state}")
    logging.info(f"Request URL: {request.url}")
    logging.info(f"Request args: {request.args}")

    # Check for errors from Google
    error = request.args.get('error')
    if error:
        logging.error(f"OAuth Error from Google: {error}")
        return redirect(url_for('index', oauth_error=error))

    # Check state for CSRF protection
    if not state or state != request.args.get('state'):
        logging.error("OAuth state mismatch.")
        return redirect(url_for('index', oauth_error='State mismatch error.'))

    flow = get_google_flow()
    if not flow:
        return redirect(url_for('index', oauth_error='Configuration error.'))

    try:
        # Use the full authorization response URL
        authorization_response = request.url
        # Ensure HTTPS if not running locally (OAUTHLIB_INSECURE_TRANSPORT is set)
        # Flask usually handles this correctly based on request scheme
        # if not os.environ.get("OAUTHLIB_INSECURE_TRANSPORT") and not app.debug:
        #      authorization_response = authorization_response.replace("http://", "https://")

        logging.info(f"Fetching token with response URL: {authorization_response}")
        flow.fetch_token(authorization_response=authorization_response)

        credentials = flow.credentials
        session['google_credentials'] = credentials_to_dict(credentials)
        logging.info("Google OAuth successful. Credentials stored in session.")

        # Optional: Save token locally for persistence across server restarts
        # Use with caution in production - secure storage needed
        try:
            with open(TOKEN_FILE, 'wb') as token_file:
                pickle.dump(credentials, token_file)
            logging.info(f"Token saved to {TOKEN_FILE}")
        except Exception as e:
            logging.warning(f"Could not save token to {TOKEN_FILE}: {e}")

        # Redirect back to index page with success message
        return redirect(url_for('index', oauth_success='true'))

    except Exception as e:
        logging.error(f"Error fetching OAuth token: {e}")
        return redirect(url_for('index', oauth_error=f'Failed to fetch token: {e}'))


@app.route('/api/summarize_emails', methods=['GET'])
def api_summarize_emails():
    """API endpoint called by JavaScript to get email summary."""
    if 'gemini_api_key' not in session:
        return jsonify({"error": "Gemini API key not configured"}), 401
    credentials = get_credentials_from_session()
    if not credentials:
         return jsonify({"error": "Google account not authenticated or token expired"}), 401

    try:
        # Configure Gemini (needed per request if not globally configured securely)
        genai.configure(api_key=session['gemini_api_key'])
        model = genai.GenerativeModel("gemini-1.5-flash") # Use flash as requested

        # Build Gmail service
        gmail_service = build('gmail', 'v1', credentials=credentials)

        # Fetch emails
        max_results = request.args.get('count', 3, type=int)
        email_snippets = fetch_recent_emails(gmail_service, max_results=max_results)

        if not email_snippets:
            return jsonify({"summary": "No recent emails found."})

        email_context = "\n---\n".join(email_snippets)
        logging.info(f"Context for Gemini ({len(email_snippets)} emails): {email_context[:200]}...") # Log snippet

        # Generate summary using Gemini
        prompt = f"Summarize the following recent email snippets concisely and professionally:\n{email_context}"
        response = model.generate_content(prompt)
        logging.info("Gemini summary generated successfully.")

        return jsonify({"summary": response.text})

    except Exception as e:
        logging.error(f"Error in /api/summarize_emails: {e}")
        # Check if it's an auth error specifically
        if "invalid_grant" in str(e).lower() or "token has been expired" in str(e).lower():
             session.pop('google_credentials', None) # Clear expired creds
             return jsonify({"error": f"Google authentication error: {e}. Please re-authenticate."}), 401
        return jsonify({"error": f"An error occurred: {e}"}), 500

# --- Add other API endpoints here (Calendar, Follow-up, Reports) ---
# Example placeholder:
@app.route('/api/schedule_meeting', methods=['POST'])
def api_schedule_meeting():
     if 'gemini_api_key' not in session:
        return jsonify({"error": "Gemini API key not configured"}), 401
     credentials = get_credentials_from_session()
     if not credentials:
         return jsonify({"error": "Google account not authenticated or token expired"}), 401

     # TODO: Get details from request.json (summary, time, etc.)
     # TODO: Build calendar_service
     # TODO: Call schedule_event function (adapted from notebook)
     # TODO: Return success/error JSON

     return jsonify({"error": "Not implemented yet"}), 501


# --- Main Execution ---
if __name__ == '__main__':
    # Ensure client_secret.json exists before starting
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"CRITICAL ERROR: '{CLIENT_SECRETS_FILE}' not found.")
        print("Please download your OAuth 2.0 Client ID credentials from Google Cloud Console,")
        print(f"rename the file to '{CLIENT_SECRETS_FILE}', and place it in the same directory as app.py.")
        exit(1) # Exit if config is missing

    # Check if OAUTHLIB_INSECURE_TRANSPORT is set for local HTTP testing
    # DO NOT use this in production
    if 'OAUTHLIB_INSECURE_TRANSPORT' not in os.environ:
        print("\nWARNING: Running OAuth over HTTP. Set environment variable OAUTHLIB_INSECURE_TRANSPORT=1")
        print("         if you are testing locally and understand the risks.")
        print("         For production, use HTTPS.\n")
        # Uncomment below to enforce HTTPS check (recommended for non-local)
        # exit("OAuth requires HTTPS or OAUTHLIB_INSECURE_TRANSPORT=1 for local testing.")


    port = int(os.environ.get('PORT', 5000))
    # Set debug=False for production
    app.run(debug=True, port=port) # Use debug=True for development (auto-reloads)
