# Data Submission App

This is a Streamlit application that allows users to input Client, BRM, LOB, and specific Details data (DataA, DataB, DataC, DataD) and saves the submissions to an Excel file.

## Setup

1.  **Install Dependencies:**
    It is recommended to use a virtual environment.
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the Application:**
    ```bash
    streamlit run app.py
    ```

## Features

-   **Input Form:** structured input for Client information and Details.
-   **Excel Storage:** Automatically creates `data_submission.xlsx` if it doesn't exist, or appends to it if it does.
-   **Timestamps:** Records the time of submission.
