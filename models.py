from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class JobExecutionLog(Base):
    __tablename__ = "job_execution_logs"
    id = Column(Integer, primary_key=True)
    job_id = Column(String)
    exit_code = Column(Integer)
    execution_time = Column(Float)
    timestamp = Column(DateTime)

def init_db(db_path):
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()
