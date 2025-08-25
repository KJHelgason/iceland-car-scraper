import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Create DB engine
engine = create_engine(DATABASE_URL)

# Create tables if they don't exist
Base.metadata.create_all(engine)

# Session factory
SessionLocal = sessionmaker(bind=engine)
