from telethon import TelegramClient, events, connection, Button
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
import asyncio
import logging
import telebot
import random
import string
from telebot import types
from modules.models import session, User, Subscription, Admin, Payment, Code, Session, SubscriptionPlan, Base, db_url
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from contextlib import asynccontextmanager
from modules.params import TELEGRAM_TOKEN, DB_URL, API_ID, API_HASH
from apscheduler.schedulers.background import BackgroundScheduler

class Bot:
    def __init__(self, api_id, api_hash, token, db_uri, connection=None, proxy=None):
        self.token = token  # Store the token as an attribute
        self.client = TelegramClient('bot_session', api_id, api_hash, proxy=proxy)
        self.engine = create_engine(db_uri, echo=True, pool_size=10, max_overflow=20)
        self.SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=self.engine))

        Base.metadata.create_all(bind=self.engine)
        self.user_plan_choice = {} 

    @asynccontextmanager
    async def get_db_session(self):
        """Provide a transactional scope around a series of operations."""
        db = self.SessionLocal()
        try:
            yield db
        except Exception as e:
            db.rollback()  # Roll back the transaction in case of error
            raise e
        finally:
            db.close()

    async def start(self):
        await self.client.start(bot_token=self.token)
        await self.setup_handlers()
        await self.client.run_until_disconnected()

    async def setup_handlers(self):
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start(event):
            await self.send_welcome(event)

        @self.client.on(events.NewMessage(pattern='/status'))
        async def check_status(event):
            await self.handle_check_status(event)

        @self.client.on(events.NewMessage(pattern='/subscribe'))
        async def subscribe(event):
            await self.handle_subscribe(event)

        @self.client.on(events.NewMessage(pattern='/generate_code'))
        async def generate_code(event):
            await self.generate_redemption_code(event)

        @self.client.on(events.NewMessage(pattern='/redeem'))
        async def redeem(event):
            await self.redeem_code(event)

        @self.client.on(events.NewMessage(func=lambda e: e.photo))
        async def handle_photo(event):
            await self.handle_receipt_photo(event)

        @self.client.on(events.CallbackQuery())
        async def callback_query(event):
            await self.handle_callback_query(event)

    async def handle_callback_query(self, event):
        data = event.data.decode('utf-8')
        chat_id = event.sender_id

        if data.startswith('subscribe_'):
            await self.subscribe_callback(chat_id, data)
        elif data.startswith('pay_online_') or data.startswith('pay_direct_'):
            await self.payment_method_callback(chat_id, data)
        elif data.startswith('approve_') or data.startswith('deny_'):
            await self.handle_admin_decision(event)

        # ... more conditions based on the callback data ...

        # Make sure to answer the callback query
        await event.answer()

    async def handle_check_status(self, event):
        chat_id = event.sender_id
        try:
            async with self.get_db_session() as session:
                user = session.query(User).filter_by(user_id=chat_id).first()
                if user:
                    if user.subscription_status == 'active':
                        expiry = user.subscription_expiry.strftime("%Y-%m-%d") if user.subscription_expiry else "an unknown time"
                        reply = f"Your subscription is active until {expiry}."
                    else:
                        reply = "You do not have an active subscription."
                else:
                    reply = "You are not registered in our database."
            
            await event.respond(reply)
        except Exception as e:
            logging.error(f"An error occurred: {e}")
            await event.respond("An error occurred while checking your status.")

    async def send_welcome(self, event):
        # Extract user data from the event
        user_id = event.sender_id
        first_name = event.chat.first_name
        # last_name = ... # Telethon does not directly provide last name, it depends on how you retrieve the user's full name
        username = event.chat.username

        # Start a new database session
        async with self.get_db_session() as session:
            # Check if the user already exists in the database
            existing_user = session.query(User).filter_by(user_id=user_id).first()

            if existing_user:
                reply = f"Welcome back {existing_user.first_name}! Use /subscribe to manage your subscription or /status to check your current subscription status."
            else:
                # Create a new user in the database
                new_user = User(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name='?',  # Update accordingly
                    subscription_status='inactive',
                )
                session.add(new_user)
                await session.commit()
                reply = "Welcome to the Subscription Manager Bot! You have been registered. Use /subscribe to choose a subscription plan."

            # Send the welcome message
            await event.respond(reply)

    async def handle_subscribe(self, event):
        chat_id = event.sender_id
        try:
            async with self.get_db_session() as session:
                plans = session.query(SubscriptionPlan).all()
                if plans:
                    buttons = [
                        [Button.inline(f"{plan.name} - ${plan.price} for {plan.duration_days} days", data=f"subscribe_{plan.plan_id}")]
                        for plan in plans
                    ]
                    await event.respond("Please choose a subscription plan:", buttons=buttons)
                else:
                    await event.respond("There are currently no subscription plans available.")
        except Exception as e:
            logging.error(f"An error occurred: {e}")
            await event.respond("An error occurred while processing your request.")

    async def subscribe_callback(self, chat_id, data):
        # Extract the plan ID from the callback data
        plan_id = int(data.split('_')[1])

        # Retrieve the selected plan details from the database
        async with self.get_db_session() as session:
            selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
            if selected_plan:
                buttons = [
                    [Button.inline("Pay Online", data=f"pay_online_{plan_id}")],
                    [Button.inline("Direct Payment", data=f"pay_direct_{plan_id}")]
                ]
                await self.client.send_message(chat_id, f"You have selected the {selected_plan.name} plan. Please choose your payment method:", buttons=buttons)
            else:
                await self.client.send_message(chat_id, "The selected plan does not exist.")

    async def payment_method_callback(self, chat_id, data):
        payment_method, plan_id = data.split('_')[1:]
        if payment_method == 'online':
            # Online payment handling logic goes here
            pass
        elif payment_method == 'direct':
            await self.handle_direct_payment(chat_id, int(plan_id))
        else:
            await self.client.send_message(chat_id, "Unrecognized payment method.")

    async def handle_direct_payment(self, chat_id, plan_id):
        async with self.get_db_session() as session:
            selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
            if selected_plan:
                # Create a new payment record
                new_payment = Payment(
                    user_id=chat_id,
                    plan_id=plan_id,
                    amount=selected_plan.price,
                    payment_method='direct',
                    payment_status='pending',
                    payment_date=datetime.utcnow()
                )
                session.add(new_payment)
                session.commit()  # Removed 'await' here

                await self.client.send_message(chat_id, "To complete your subscription via direct payment, please transfer the payment to our account and provide us with the receipt number.")
            else:
                await self.client.send_message(chat_id, "The selected plan does not exist.")

    async def handle_receipt_photo(self, event):
        chat_id = event.sender_id
        async with self.get_db_session() as session:
            # Assuming that there is a Payment record with 'pending' status for the user
            payment = session.query(Payment).filter_by(user_id=chat_id, payment_status='pending').first()
            if payment:
                # Forward the photo to each admin
                admins = await self.get_all_admins(session)
                for admin_id in admins:
                    await event.forward_to(admin_id)
                    # Create inline buttons for approval or denial
                    approve_button = Button.inline("Approve", data=f"approve_{chat_id}_{payment.payment_id}")
                    deny_button = Button.inline("Deny", data=f"deny_{chat_id}_{payment.payment_id}")
                    await self.client.send_message(admin_id, "Please approve or deny the payment:", buttons=[approve_button, deny_button])
                # Update the payment record with receipt information
                payment.receipt_message_id = event.message.id
                session.commit()  # Assuming this is a synchronous operation
            else:
                await event.respond("No pending payment found or you've already submitted a receipt.")

    async def handle_admin_decision(self, event):
        data = event.data.decode('utf-8')
        decision, user_id, payment_id = data.split('_')
        admin_id = event.sender_id  # Admin who made the decision

        if decision == 'approve':
            await self.process_approval(int(user_id), int(payment_id))
            decision_text = "You approved this payment."
        elif decision == 'deny':
            await self.process_denial(int(user_id), int(payment_id))
            decision_text = "You denied this payment."

        # Edit the original message sent to the admin
        await self.client.edit_message(admin_id, event.query.msg_id, decision_text, buttons=None)


    async def process_approval(self, user_id, payment_id):
        async with self.get_db_session() as session:
            payment = session.query(Payment).filter_by(payment_id=payment_id).first()
            if payment:
                payment.payment_status = 'confirmed'
                session.commit()
                await self.update_user_subscription(user_id, payment_id)
                await self.client.send_message(user_id, "Your payment has been approved. Your subscription has been updated.")
            else:
                logging.error(f"No payment found for payment ID {payment_id}.")


    async def process_denial(self, user_id, payment_id):
        async with self.get_db_session() as session:
            payment = session.query(Payment).filter_by(payment_id=payment_id).first()
            if payment:
                payment.payment_status = 'denied'
                session.commit()
                await self.client.send_message(user_id, "Your payment was not accepted. Please contact support for more information.")
            else:
                logging.error(f"No payment found for payment ID {payment_id}.")

    async def generate_redemption_code(self, event):
        if not await self.is_admin(event.sender_id):
            await event.respond("You are not authorized to generate codes.")
            return

        # Extract the duration from the command
        command_parts = event.raw_text.split()
        if len(command_parts) < 2 or not command_parts[1].isdigit():
            await event.respond("Please provide a valid duration in days. Usage: /generate_code <duration>")
            return
        
        duration = int(command_parts[1])
        if duration <= 0:
            await event.respond("Duration must be positive.")
            return

        # Generate the code
        code = self.create_unique_code()
        async with self.get_db_session() as session:
            new_code = Code(
                code=code,
                associated_days=duration,
                used_status=False
            )
            session.add(new_code)
            session.commit()  # Assuming synchronous operation

        await event.respond(f"Generated code: {code} for {duration} days")

    def create_unique_code(self):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

    async def is_admin(self, user_id):
        async with self.get_db_session() as session:
            admin = session.query(Admin).filter_by(admin_id=user_id).first()
            return admin is not None
        
    async def get_all_admins(self, session):
        admins = session.query(Admin).all()
        return [admin.admin_id for admin in admins]
        
    async def redeem_code(self, event):
        # Extract the code from the command
        command_parts = event.raw_text.split()
        if len(command_parts) < 2:
            await event.respond("Please provide the redemption code. Usage: /redeem <code>")
            return
        
        code_text = command_parts[1].strip().upper()

        user_id = event.sender_id
        async with self.get_db_session() as session:
            code = session.query(Code).filter_by(code=code_text, used_status=False).first()
            if code:
                code.used_status = True
                associated_days = code.associated_days
                session.commit()  # Assuming synchronous operation
                await self.update_user_subscription(user_id, additional_days=associated_days)
                await event.respond(f"Your code has been redeemed successfully. Subscription extended by {associated_days} days.")
            else:
                await event.respond("The code is invalid or has already been used.")

    async def update_user_subscription(self, user_id, payment_id=None, additional_days=None):
        async with self.get_db_session() as session:
            # Find the user in the database
            user = session.query(User).filter_by(user_id=user_id).first()
            if not user:
                await self.client.send_message(user_id, "User not found in the database.")
                return

            # If payment_id is provided, use it to find the subscription plan and calculate additional days
            if payment_id:
                payment = session.query(Payment).filter_by(payment_id=payment_id).first()
                if payment and payment.payment_status == 'confirmed':
                    selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=payment.plan_id).first()
                    if selected_plan:
                        additional_days = selected_plan.duration_days
                else:
                    await self.client.send_message(user_id, "Payment not found or not confirmed.")
                    return

            # Update the user's subscription expiry and status
            if additional_days:
                new_expiry_date = (user.subscription_expiry + timedelta(days=additional_days)) if user.subscription_expiry else (datetime.utcnow() + timedelta(days=additional_days))
                user.subscription_expiry = new_expiry_date
                user.subscription_status = 'active'
                session.commit()
                await self.client.send_message(user_id, f"Your subscription has been updated and is active until {new_expiry_date.strftime('%Y-%m-%d %H:%M:%S')}.")
            else:
                await self.client.send_message(user_id, "No additional days provided for the subscription update.")
                

if __name__ == '__main__':
    bot = Bot(api_id=API_ID, api_hash=API_HASH, token=TELEGRAM_TOKEN, db_uri=DB_URL)
    asyncio.run(bot.start())
