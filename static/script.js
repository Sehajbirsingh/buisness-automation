document.addEventListener('DOMContentLoaded', () => {
    const summarizeBtn = document.getElementById('summarize-btn');
    const summaryLoading = document.getElementById('summary-loading');
    const summaryError = document.getElementById('summary-error');
    const summaryResultDiv = document.getElementById('summary-result');
    const summaryResultPre = summaryResultDiv ? summaryResultDiv.querySelector('pre') : null;

    if (summarizeBtn) {
        summarizeBtn.addEventListener('click', async () => {
            // Reset previous state
            summaryLoading.style.display = 'block';
            summaryError.style.display = 'none';
            summaryError.textContent = '';
            summaryResultDiv.style.display = 'none';
            if (summaryResultPre) summaryResultPre.textContent = '';
            summarizeBtn.disabled = true;

            try {
                // Make API call to the Flask backend
                const response = await fetch('/api/summarize_emails'); // Relative URL works

                if (!response.ok) {
                    // Try to get error message from JSON response
                    let errorMsg = `HTTP error! Status: ${response.status}`;
                    try {
                        const errorData = await response.json();
                        errorMsg = errorData.error || errorMsg;
                         // If it's an auth error, maybe reload or show specific message
                        if (response.status === 401) {
                             errorMsg += " Please try authenticating with Google again.";
                             // Optionally, redirect or show auth button if possible
                        }
                    } catch (e) {
                        // Ignore if response is not JSON
                    }
                    throw new Error(errorMsg);
                }

                const data = await response.json();

                // Display the summary
                if (data.summary && summaryResultPre) {
                    summaryResultPre.textContent = data.summary;
                    summaryResultDiv.style.display = 'block';
                } else if (data.error) {
                     throw new Error(data.error);
                } else {
                    // Handle unexpected response format
                     throw new Error("Received an unexpected response format from the server.");
                }

            } catch (error) {
                console.error('Error fetching email summary:', error);
                summaryError.textContent = `Error: ${error.message}`;
                summaryError.style.display = 'block';
            } finally {
                // Re-enable button and hide loading indicator
                summaryLoading.style.display = 'none';
                summarizeBtn.disabled = false;
            }
        });
    } else {
        console.log("Summarize button not found on this page.");
    }

    // Add event listeners for other features here when implemented
});
