## Expense with friends / Vibe coded with Gemini 2.5

This project is a web application designed to help groups of people manage shared expenses, similar to the popular Tricount application. It allows users to create trips, add participants, record expenses, and calculate who owes whom to settle balances.
Project Goal

The primary goal of this project is to provide a simple and effective tool for tracking shared expenses during group activities like trips, events, or household budgeting. It aims to offer core functionalities found in expense-splitting applications, focusing on ease of use and clear visualization of spending.
Current Features

As of the current development stage, the application includes the following features:

- Trip Management: Create and manage different trips.

- Participant Management: Add and edit participants within each trip.

- Expense Tracking:
    - Record expenses with a description, amount, and date.
    - Specify who paid for the expense.
    - Define how the expense is split among participants using a weight system (integer weights).
    - Edit and delete existing expenses.

- Default Split (Weights): Set default expense splitting weights for participants in a specific trip.

- PDF Import: Import expenses from a PDF report. The application attempts to guess the category of imported expenses based on previously categorized expenses with similar descriptions.

- Expense Listing: View all expenses for a trip, sorted by date (most recent first).

- Search and Filtering: Search expenses by description on the trip details page.

- Monthly Grouping: Expenses in the list are grouped by month and year for better organization.

- Category Management:
    - Create, list, and delete expense categories (e.g., Food, Transport, Accommodation).
    - Categories are generic and can be used across all trips.

- Expense Statistics: View a pie chart showing the distribution of expenses by category for the current trip.

- Date Range Filtering for Chart: Filter the expense data used for the category distribution chart by a specific start and end date.

- Balance Calculation: View a summary of balances showing who owes whom.

- Simplified Transactions: See a simplified list of transactions needed to settle balances.

## Technologies Used

- Backend: Flask (Python)

- Database: PostgreSQL (managed with Docker Compose) or SQLite for local development.

- Frontend: HTML, CSS (using Tailwind CSS for styling), JavaScript (using Chart.js for the expense distribution chart).

- Dependency Management: Likely pip and a requirements.txt file (standard Python practice).

- Containerization: Docker Compose for database setup.

## Setup and Installation

- Set up Database:
    - Using Docker Compose (Recommended for PostgreSQL):

        Ensure Docker is installed and running.

        Create a .env file in the project root with your database credentials (refer to .env - Database Credentials immersive).

        Run docker-compose up -d db to start the PostgreSQL container.

        Ensure your DATABASE_URL environment variable is set correctly to connect to the PostgreSQL database (e.g., postgresql://tricount_user:your_strong_password@localhost:5432/tricount_db).

    - Using SQLite (Simpler for local development):

        Ensure your DATABASE_URL environment variable is set to sqlite:///./tricount.db.

- Install Dependencies:

    `pip install -r requirements.txt`

    (You may need to create a requirements.txt file listing the project's Python dependencies like Flask, SQLAlchemy, psycopg2-binary (if using PostgreSQL), etc.)

- Initialize the Database:

    Run the database initialization script (e.g., `python -c 'from database import init_db; init_db()'`). Note: If using SQLite and changing the schema, you might need to delete the existing .db file first. For production, database migrations (e.g., Alembic) are recommended.

- Run the Application:

    `python app.py`

    Access the Application: Open your web browser and go to http://127.0.0.1:5000/ (or the address Flask is running on).

