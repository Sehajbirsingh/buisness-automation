from flask import Flask, request, render_template
from productivity_core import (
    full_productivity_flow,
    summarize_emails,
    send_onboarding_email,
    schedule_onboarding_meeting,
    generate_report,
    fill_out_form,
    follow_up_email
)
import os

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        email = request.form.get("email")
        meeting_time = request.form.get("meeting_time")
        task = request.form.get("task")
        uploaded_files = request.files.getlist("files")

        # Save uploaded files
        file_paths = []
        for file in uploaded_files:
            if file and file.filename:
                path = os.path.join("uploads", file.filename)
                os.makedirs("uploads", exist_ok=True)
                file.save(path)
                file_paths.append(path)

        # Task routing
        if task == "full":
            result = full_productivity_flow(email, meeting_time, file_paths)
        elif task == "summarize":
            result = summarize_emails(file_paths)
        elif task == "send_email":
            body = "Welcome to the team! We are excited to onboard you."
            result = send_onboarding_email(email, body)
        elif task == "schedule_meeting":
            result = schedule_onboarding_meeting(meeting_time)
        elif task == "generate_report":
            result = generate_report(file_paths)
        elif task == "fill_form":
            result = fill_out_form(file_paths)
        elif task == "follow_up":
            result = follow_up_email(file_paths)
        else:
            result = "❌ Unknown task."

        return render_template("result.html", result=result, email=email, meeting_time=meeting_time)

    return render_template("index.html")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

