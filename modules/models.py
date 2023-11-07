from sqlalchemy import create_engine, Column, Integer, String, Boolean, Date, ForeignKey, Numeric, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    user_id = Column(BigInteger, primary_key=True)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    subscription_status = Column(String)
    subscription_expiry = Column(Date)
    subscriptions = relationship('Subscription', back_populates='user')

class Subscription(Base):
    __tablename__ = 'subscriptions'
    subscription_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id'))
    plan_type = Column(String)
    start_date = Column(Date)
    end_date = Column(Date)
    payment_status = Column(String)
    user = relationship('User', back_populates='subscriptions')

class Admin(Base):
    __tablename__ = 'admins'
    admin_id = Column(BigInteger, primary_key=True)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    is_superuser = Column(Boolean)

class Payment(Base):
    __tablename__ = 'payments'
    payment_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.user_id'))
    plan_id = Column(Integer, ForeignKey('subscription_plans.plan_id'))  # This assumes your SubscriptionPlan model uses plan_id as the primary key
    amount = Column(Numeric(10, 2))
    payment_method = Column(String)
    payment_status = Column(String)
    payment_date = Column(Date)
    admin_approval_message_id = Column(BigInteger)  # New field to store the message ID for admin approval
    receipt_info = Column(String)
    receipt_message_id = Column(BigInteger)

class Code(Base):
    __tablename__ = 'codes'
    code = Column(String, primary_key=True)
    code_type = Column(String)
    associated_days = Column(Integer)
    discount_amount = Column(Numeric(10, 2))
    expiry_date = Column(Date)
    used_status = Column(Boolean)
    user_id = Column(BigInteger, ForeignKey('users.user_id'))

class SubscriptionPlan(Base):
    __tablename__ = 'subscription_plans'
    plan_id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, unique=True)
    name = Column(String, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    duration_days = Column(Integer, nullable=False)  # Duration of the plan in days


# Replace 'postgresql://user:password@localhost/mydatabase' with your actual database URL
engine = create_engine('')
# Base.metadata.drop_all(engine)

Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)
session = Session()
