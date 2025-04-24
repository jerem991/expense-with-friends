import os
from flask import Flask, render_template, request, redirect, url_for, flash
# Import necessary models and database session
from database import init_db, SessionLocal
# Import the trip blueprint
from trip_blueprint import trip_blueprint
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# Secret key is needed for session management and flashing messages
app.secret_key = os.environ.get('SECRET_KEY', 'a_super_secret_key')
# Configure upload folder (still needed for mockup function signature in utils)
app.config['UPLOAD_FOLDER'] = 'uploads'
# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# Initialize the database
init_db()

# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Register the trip blueprint
app.register_blueprint(trip_blueprint)


@app.route('/')
def index():
    """Displays a list of all trips."""
    db = next(get_db())
    # Import Trip model here as it's used in this route
    from database import Trip
    trips = db.query(Trip).all()
    return render_template('index.html', trips=trips)

@app.route('/create_trip', methods=['GET', 'POST'])
def create_trip():
    """Handles creating a new trip."""
    db = next(get_db())
    # Import Trip model here as it's used in this route
    from database import Trip
    if request.method == 'POST':
        trip_name = request.form['trip_name']
        if trip_name:
            new_trip = Trip(name=trip_name)
            db.add(new_trip)
            db.commit()
            db.refresh(new_trip)
            flash(f"Trip '{trip_name}' created successfully!", 'success')
            # Use blueprint name in url_for for redirect
            return redirect(url_for('trip_blueprint.view_trip', trip_id=new_trip.id))
        else:
            flash("Trip name cannot be empty.", 'danger')
            return render_template('create_trip.html')

    return render_template('create_trip.html')


if __name__ == '__main__':
    # In a production environment, you would use a production-ready WSGI server
    # like Gunicorn or uWSGI instead of app.run().
    # debug=True should be False in production
    app.run(debug=True, host='0.0.0.0')
