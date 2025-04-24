import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

# Use an environment variable for the database URL
# Defaults to a SQLite database named 'tricount.db' in the current directory
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./tricount.db")

# Create a SQLAlchemy engine
# The connect_args={"check_same_thread": False} is ONLY needed for SQLite
# when used with Flask's default single-threaded server.
# We should remove it to support other databases like PostgreSQL.
if DATABASE_URL.startswith("sqlite:///"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # For other databases (like PostgreSQL), remove the check_same_thread argument
    engine = create_engine(DATABASE_URL)


# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for declarative models
Base = declarative_base()

# Define Database Models
class Trip(Base):
    """Represents a trip."""
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    participants = relationship("Participant", back_populates="trip", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="trip", cascade="all, delete-orphan")
    participant_default_proportions = relationship("TripParticipantDefaultProportion", back_populates="trip", cascade="all, delete-orphan")


class Participant(Base):
    """Represents a participant in a trip."""
    __tablename__ = "participants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    avatar_url = Column(String, nullable=True) # Reusing this for emoji
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    trip = relationship("Trip", back_populates="participants")
    # expenses_paid = relationship("Expense", back_populates="payer") # This is handled by payer relationship in Expense
    default_proportions = relationship("TripParticipantDefaultProportion", back_populates="participant", cascade="all, delete-orphan")

class Category(Base):
    """Represents a generic expense category."""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True) # Category names should be unique
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship to expenses
    expenses = relationship("Expense", back_populates="category")


class Expense(Base):
    """Represents an expense within a trip."""
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(String)
    amount = Column(Float)
    expense_date = Column(DateTime)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    paid_by_id = Column(Integer, ForeignKey("participants.id"))
    # Store proportions as a JSON string (now represents weights)
    proportions = Column(Text, nullable=True)
    date_added = Column(DateTime, default=datetime.utcnow)
    last_modified = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # New foreign key to the Category table
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)


    # Relationships
    trip = relationship("Trip", back_populates="expenses")
    payer = relationship("Participant", backref="expenses_paid") # Renamed backref for clarity
    # New relationship to the Category table
    category = relationship("Category", back_populates="expenses")


class TripParticipantDefaultProportion(Base):
    """Represents the default proportion/weight for a participant in a specific trip."""
    __tablename__ = "trip_participant_default_proportions"

    trip_id = Column(Integer, ForeignKey("trips.id"), primary_key=True)
    participant_id = Column(Integer, ForeignKey("participants.id"), primary_key=True)
    # This column now stores the default WEIGHT for the participant in this trip
    default_proportion = Column(Float, default=1.0) # Default weight is 1

    # Relationships
    trip = relationship("Trip", back_populates="participant_default_proportions")
    participant = relationship("Participant", back_populates="default_proportions")


# Function to create database tables
def init_db():
    """Creates all database tables."""
    # Check if tables already exist before creating
    # This avoids errors if init_db is called multiple times
    # In a real application, you'd use migrations (e.g., Alembic)
    # to manage database schema changes.
    # For this example, we'll just try to create and ignore if they exist.
    try:
        Base.metadata.create_all(bind=engine)
        print("Database tables checked/created.")
    except Exception as e:
        # This might catch errors if the database URL is invalid or permissions are wrong
        print(f"Error during database initialization: {e}")
        # Depending on the error, you might want to re-raise or handle differently


# Example of how to use the session (for testing or initial data setup)
# def create_trip_example():
#     db = SessionLocal()
#     new_trip = Trip(name="Summer Vacation 2024")
#     db.add(new_trip)
#     db.commit()
#     db.refresh(new_trip)
#     print(f"Created trip: {new_trip.name} with ID: {new_trip.id}")
#     db.close()

# if __name__ == "__main__":
#     init_db()
#     # create_trip_example()
