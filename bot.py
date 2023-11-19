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
from contextlib import contextmanager
from modules.params import TELEGRAM_TOKEN, DB_URL
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO)


TOKEN = TELEGRAM_TOKEN

class Bot:
    def __init__(self, 
                 bot=telebot.TeleBot(token=TOKEN),
                #  menu=MainMenu(), 
                 db_uri=DB_URL):
        self.bot = bot
        self.engine = create_engine(db_uri, echo=True, pool_size=10, max_overflow=20)
        self.SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=self.engine))
        Base.metadata.create_all(bind=self.engine)
        self.user_plan_choice = {} 


    @contextmanager
    def get_db_session(self):
        """Provide a transactional scope around a series of operations."""
        db = self.SessionLocal()
        try:
            yield db
        except Exception as e:
            db.rollback()  # Roll back the transaction in case of error
            raise e
        finally:
            db.close()

    async def start_polling(self):
        # Start the bot and run it until it is disconnected
        await self.client.run_until_disconnected()

    def start_scheduler(self):
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(self.check_subscriptions, 'interval', hours=24)  # Run daily
        self.scheduler.start()
    
    def check_subscriptions(self):
        with self.get_db_session() as session:
            current_date = datetime.utcnow()
            users = session.query(User).all()
            for user in users:
                if user.subscription_expiry and user.subscription_expiry < current_date:
                    # Notify admins to remove the user
                    self.notify_admins_for_removal(user.user_id, user.first_name, user.username)
                elif user.subscription_expiry and user.subscription_expiry - timedelta(days=3) <= current_date:
                    # Notify users about upcoming expiry
                    self.notify_admins_for_expiry(user.user_id, user.first_name, user.username)
                    self.bot.send_message(user.user_id, "Your subscription is about to expire in 3 days.")

    def notify_admins_for_expiry(self, user_id, first_name, user_name):
        admins = self.get_all_admins()
        for admin_id in admins:
            self.bot.send_message(admin_id, f"User {user_id}'s with username: {user_name} and name: {first_name} subscription has 3 days to be expired.")

    def notify_admins_for_removal(self, user_id, first_name, user_name):
        admins = self.get_all_admins()
        for admin_id in admins:
            self.bot.send_message(admin_id, f"User {user_id}'s with username: {user_name} and name: {first_name} subscription has expired. Consider removing them from the channel.")

    def send_welcome(self, message):
        # Extract user data from the message
        user_id = message.from_user.id
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        username = message.from_user.username  # Some users might not have a username

        # Start a new database session
        with Session() as session:
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
                    last_name=last_name,
                    subscription_status='inactive',
                    # Set the subscription_expiry to None or a default value as needed
                )
                session.add(new_user)
                session.commit()
                reply = "Welcome to the Subscription Manager Bot! You have been registered. Use /subscribe to choose a subscription plan."

            # Send the welcome message
            self.bot.reply_to(message, reply)

    def channel_id_check(self, message):
        if message.forward_from_chat:
            channel_id = message.forward_from_chat.id
            self.bot.send_message(message.chat.id, f"Channel ID: {channel_id}")
            print("Channel ID:", channel_id)

    def check_status(self, message):
        chat_id = message.chat.id
        print(f"Received /status command from {chat_id}.")  # Debug print
        try:
            print("Attempting to create a session...")  # Debug print
            with Session() as session:
                print("Session created, querying the user...")  # Debug print
                user = session.query(User).filter_by(user_id=chat_id).first()
                if user:
                    if user.subscription_status == 'active':
                        expiry = user.subscription_expiry.strftime("%Y-%m-%d %H:%M:%S") if user.subscription_expiry else "an unknown time"
                        reply = f"Your subscription is active until {expiry}."
                    else:
                        reply = "You do not have an active subscription."
                else:
                    reply = "You are not registered in our database."
                print(f"Replying with: {reply}")  # Debug print
            self.bot.reply_to(message, reply)
        except Exception as e:
            print(f"An error occurred: {e}")
            self.bot.reply_to(message, "An error occurred while checking your status.")

    def check_subscriptions(self):
        with self.get_db_session() as session:
            # Fetch all users
            users = session.query(User).all()
            for user in users:
                if user.subscription_expiry and user.subscription_expiry <= datetime.utcnow():
                    # Remove user from the channel if subscription expired
                    self.remove_user_from_channel(user.user_id)
                elif user.subscription_expiry and datetime.utcnow() + timedelta(days=3) >= user.subscription_expiry:
                    # Notify user and admins if subscription is about to expire
                    self.bot.send_message(user.user_id, "Your subscription is about to expire in 3 days.")
                    self.notify_admins_for_renewal(user.user_id)

    def notify_admins_for_renewal(self, user_id):
        admins = self.get_all_admins()
        notification_message = f"User {user_id}'s subscription is about to expire."
        for admin_id in admins:
            self.bot.send_message(admin_id, notification_message)

    def subscribe(self, message):
        chat_id = message.chat.id
        with Session() as session:
            plans = session.query(SubscriptionPlan).all()
            if plans:
                markup = types.InlineKeyboardMarkup()
                for plan in plans:
                    button_text = f"{plan.name} - ${plan.price} for {plan.duration_days} days"
                    markup.add(types.InlineKeyboardButton(button_text, callback_data=f"subscribe_{plan.plan_id}"))
                self.bot.send_message(chat_id, "Please choose a subscription plan:", reply_markup=markup)
            else:
                self.bot.send_message(chat_id, "There are currently no subscription plans available.")

    def callback_query(self, call):
        chat_id = call.message.chat.id
        plan_id = int(call.data.split('_')[1])  # This extracts the plan ID from the callback data
        print(f'THIS IS PLAN IDDDDD: {plan_id}')
        # Retrieve the selected plan details from the database
        with Session() as session:
            selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
            print(f'SELECTED PLAN: {selected_plan}')
            if selected_plan:
                # Proceed to payment method selection
                markup = types.InlineKeyboardMarkup()
                # Assuming you have two payment methods: 'online' and 'direct'
                markup.add(types.InlineKeyboardButton("Pay Online", callback_data=f"pay_online_{plan_id}"))
                markup.add(types.InlineKeyboardButton("Direct Payment", callback_data=f"direct_payment_{plan_id}"))
                self.bot.send_message(chat_id, f"You have selected the {selected_plan.name} plan. Please choose your payment method:", reply_markup=markup)
            else:
                self.bot.send_message(chat_id, "The selected plan does not exist.")

        # Make sure to answer the callback query
        self.bot.answer_callback_query(call.id)

    def subscribe_callback(self, call):
        chat_id = call.message.chat.id
        plan_id = int(call.data.split('_')[1])  # Extracts the plan ID from the callback data

        # Store the user's choice temporarily
        self.user_plan_choice[chat_id] = plan_id

        # Proceed to payment method selection
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Pay Online", callback_data=f"pay_online_{plan_id}"))
        markup.add(types.InlineKeyboardButton("Direct Payment", callback_data=f"pay_direct_{plan_id}"))
        self.bot.send_message(chat_id, "Please choose your payment method:", reply_markup=markup)

        # Make sure to answer the callback query
        self.bot.answer_callback_query(call.id)

    def payment_method_callback(self, call):
        chat_id = call.message.chat.id
        payment_method, plan_id = call.data.split('_')[1:]
        print(payment_method)

        if payment_method == 'online':
            # Online payment handling code goes here
            pass
        elif payment_method == 'direct':
            self.handle_direct_payment(chat_id, int(plan_id))
        else:
            self.bot.send_message(chat_id, "Unrecognized payment method.")

        # Answer the callback query
        self.bot.answer_callback_query(call.id)

    def handle_direct_payment(self, chat_id, plan_id):
        # Retrieve the selected plan details from the database
        with self.get_db_session() as session:
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
                session.commit()

                self.bot.send_message(chat_id, "To complete your subscription via direct payment, please transfer the payment to 6219861927644152 and provide us with the receipt number.")
            else:
                self.bot.send_message(chat_id, "The selected plan does not exist.")

    def handle_photo(self, message):
        chat_id = message.chat.id
        with self.get_db_session() as session:
            # Assuming that there is a Payment record with 'pending' status for the user
            payment = session.query(Payment).filter_by(user_id=chat_id, payment_status='pending').first()
            if payment:
                # Forward the photo to each admin
                admins = session.query(Admin).all()
                for admin in admins:
                    self.bot.forward_message(admin.admin_id, chat_id, message.message_id)
                    # Send the inline buttons for approval or denial to each admin
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("Approve", callback_data=f"approve_{chat_id}_{payment.payment_id}"),
                            types.InlineKeyboardButton("Deny", callback_data=f"deny_{chat_id}_{payment.payment_id}"))
                    self.bot.send_message(admin.admin_id, "Please approve or deny the payment:", reply_markup=markup)
                # Update the payment record with receipt information
                payment.receipt_message_id = message.message_id
                session.commit()
            else:
                self.bot.send_message(chat_id, "No pending payment found or you've already submitted a receipt.")

    def handle_messages(self, message):
        if message.content_type == 'photo':
            chat_id = message.chat.id
            with self.get_db_session() as session:
                # Fetch the latest pending payment for the user
                payment = session.query(Payment).filter_by(user_id=chat_id, payment_status='pending').order_by(Payment.payment_date.desc()).first()
                if payment:
                    # Update the payment record with the receipt message ID
                    payment.receipt_message_id = message.message_id
                    session.commit()

                    # Forward the receipt photo to all admins and ask for approval
                    admins = session.query(Admin).all()  # Replace with your method of retrieving admin IDs
                    for admin in admins:
                        forwarded_message = self.bot.forward_message(admin.admin_id, chat_id, message.message_id)
                        # Prepare inline buttons for approval or denial
                        markup = types.InlineKeyboardMarkup()
                        markup.row(
                            types.InlineKeyboardButton("Approve", callback_data=f"approve_{chat_id}_{payment.payment_id}"),
                            types.InlineKeyboardButton("Deny", callback_data=f"deny_{chat_id}_{payment.payment_id}")
                        )
                        # Send the inline buttons to each admin
                        self.bot.send_message(admin.admin_id, "Please approve or deny the payment:", reply_markup=markup)
                else:
                    # Notify the user if no pending payment is found
                    self.bot.send_message(chat_id, "No pending payment found or you've already submitted a receipt.")

    def handle_admin_decision(self, call):
        call_data = call.data.split('_')
        decision = call_data[0]
        user_id = int(call_data[1])
        payment_id = int(call_data[2])

        if decision == 'approve':
            self.process_approval(user_id, call.from_user.id, payment_id)
        elif decision == 'deny':
            self.process_denial(user_id, call.from_user.id, payment_id)

        # Update the admin's message to reflect the decision
        self.bot.edit_message_text(chat_id=call.from_user.id, message_id=call.message.message_id, text=f"Payment {'approved' if decision == 'approve' else 'denied'}", reply_markup=None)

    def process_approval(self, user_id, admin_id, payment_id):
        with self.get_db_session() as session:
            payment = session.query(Payment).filter_by(payment_id=payment_id).first()
            if payment:
                payment.payment_status = 'confirmed'
                session.commit()
                self.update_user_subscription(user_id, payment_id)
                # self.bot.send_message(user_id, "Your payment has been approved. Your subscription has been updated.")
            else:
                print(f"No payment found for payment ID {payment_id}.")

    def process_denial(self, user_id, admin_id, message_id):
        # Handle payment denial
        with self.get_db_session() as session:
            payment = self.find_payment_by_message_id(message_id, session)
            if payment:
                payment.payment_status = 'denied'
                session.commit()
        self.bot.send_message(user_id, "Your payment was not accepted. Please contact support for more information.")

    def find_payment_by_message_id(self, message_id, session):
        """
        Finds a payment record associated with a given message ID.

        :param message_id: The ID of the message (e.g., receipt image) sent by the user.
        :param session: The database session.
        :return: The Payment object or None if not found.
        """
        return session.query(Payment).filter_by(receipt_message_id=message_id).first()

    def update_user_subscription(self, user_id, payment_id=None, additional_days=None):
        with self.get_db_session() as session:
            if payment_id:
                payment = session.query(Payment).filter_by(payment_id=payment_id).first()
                if payment:
                    payment.payment_status = 'confirmed'
                    selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=payment.plan_id).first()
                    if selected_plan:
                        additional_days = selected_plan.duration_days

            user = session.query(User).filter_by(user_id=user_id).first()
            if user:
                # Determine the new expiry date
                new_expiry_date = user.subscription_expiry + timedelta(days=additional_days) if user.subscription_expiry else datetime.utcnow() + timedelta(days=additional_days)

                user.subscription_expiry = new_expiry_date
                user.subscription_status = 'active'  # Update subscription status as active
                session.commit()

                self.bot.send_message(user_id, "Your subscription has been updated.")

    def is_admin(self, user_id):
        with self.get_db_session() as session:
            # Query the Admin table to check if the user_id exists there
            admin = session.query(Admin).filter_by(admin_id=user_id).first()
            return admin is not None
        
    def get_all_admins(self):
        with self.get_db_session() as session:
            # Query the Admin table to get all admin records
            admins = session.query(Admin).all()
            # Extract the admin_id from each admin record
            admin_ids = [admin.admin_id for admin in admins]
            return admin_ids

    def generate_redemption_code(self, message):
        if not self.is_admin(message.from_user.id):
            self.bot.reply_to(message, "You are not authorized to generate codes.")
            return

        # Ask the admin for the duration of the code
        msg = self.bot.reply_to(message, "Enter the duration in days for the redemption code:")
        self.bot.register_next_step_handler(msg, self.ask_for_code_duration)

    def ask_for_code_duration(self, message):
        try:
            duration = int(message.text.strip())
            if duration <= 0:
                raise ValueError("Duration must be positive.")
        except ValueError:
            self.bot.reply_to(message, "Invalid input. Please enter a number representing the duration in days.")
            return

        # Generate the code
        code = self.create_unique_code()
        with self.get_db_session() as session:
            new_code = Code(
                code=code,
                associated_days=duration,
                used_status=False
            )
            session.add(new_code)
            session.commit()

        self.bot.send_message(message.chat.id, f"Generated code: {code} for {duration} days")

    def create_unique_code(self):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

    def redeem_code(self, message):
        sent = self.bot.reply_to(message, "Please enter your redemption code.")
        self.bot.register_next_step_handler(sent, self.process_redeem_code)

    def process_redeem_code(self, message):
        code_text = message.text.strip().upper()  # Assuming codes are uppercase
        user_id = message.from_user.id

        with self.get_db_session() as session:
            code = session.query(Code).filter_by(code=code_text, used_status=False).first()
            if code:
                code.used_status = True
                associated_days = code.associated_days  # Get the number of days from the code
                session.commit()
                self.update_user_subscription(user_id, additional_days=associated_days)  # Pass only additional_days
                self.bot.send_message(user_id, f"Your code has been redeemed successfully. Subscription extended by {associated_days} days.")
            else:
                self.bot.send_message(user_id, "The code is invalid or has already been used.")

#########################################
#########################################
#############ADMIN COMMANDS##############
#########################################
#########################################

    def add_admin_command(self, message):
        chat_id = message.chat.id
        # Check if the user is a superuser
        admin = session.query(Admin).filter_by(admin_id=chat_id, is_superuser=True).first()
        if admin:
            # Provide instructions on how to add an admin
            reply = "Please send the user ID of the person you want to make an admin."
            # Proceed with the next step of adding an admin
        else:
            reply = "You do not have permission to add admins."
        self.bot.reply_to(message, reply)

    def add_plan_command(self, message):
        if self.is_admin(message.from_user.id):
            try:
                msg = self.bot.reply_to(message, "Enter the new plan details in the format: name, price, duration_days")
                self.bot.register_next_step_handler(msg, self.process_add_plan)
            except Exception as e:
                logging.error(f"Error in add_plan_command: {e}")
                self.bot.reply_to(message, "An error occurred while processing your request.")
        else:
            self.bot.reply_to(message, "You are not authorized to add plans.")

    def process_add_plan(self, message):
        try:
            plan_data = message.text.split(',')
            print(plan_data)
            if len(plan_data) != 3:
                raise ValueError("Incorrect number of parameters for a new plan.")
            name = plan_data[0].strip()
            price = Decimal(plan_data[1].strip())
            duration_days = int(plan_data[2].strip())

            new_plan = SubscriptionPlan(name=name, price=price, duration_days=duration_days)

            # Add the new plan to the database
            with self.get_db_session() as session:
                session.add(new_plan)
                session.commit()

            # Inform the user that the plan has been added successfully
            self.bot.reply_to(message, f"New plan added: {name}, price: {price}, duration: {duration_days} days")

            # Rest of your code for adding a new plan
        except (IndexError, ValueError) as e:
            logging.error(f"Error in process_add_plan: {e}")
            self.bot.reply_to(message, "Incorrect plan format. Please send the data in the format: name, price, duration_days.")
        except Exception as e:
            logging.error(f"Unexpected error in process_add_plan: {e}")
            self.bot.reply_to(message, "An unexpected error occurred.")

    def delete_plan_command(self, message):
        if self.is_admin(message.from_user.id):
            with self.get_db_session() as session:
                # Fetch plans from the database and order them by price descending
                plans = session.query(SubscriptionPlan).order_by(SubscriptionPlan.price.desc()).all()
                if plans:
                    # Create inline keyboard
                    markup = types.InlineKeyboardMarkup()
                    for plan in plans:
                        # Button text contains plan name and price
                        button_text = f"{plan.name} - ${plan.price}"
                        # Callback data contains a unique identifier, e.g., "delete_1"
                        markup.add(types.InlineKeyboardButton(button_text, callback_data=f"delete_{plan.plan_id}"))
                    self.bot.send_message(message.chat.id, "Select a plan to delete:", reply_markup=markup)
                else:
                    self.bot.send_message(message.chat.id, "No subscription plans found.")
        else:
            self.bot.reply_to(message, "You are not authorized to delete plans.")

    def process_delete_plan(self, message):
        try:
            # Assuming the plan ID is an integer
            plan_id = int(message.text.strip())
            
            with Session() as session:
                # Look up the plan by ID
                plan_to_delete = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
                if plan_to_delete:
                    # Delete the plan from the database
                    session.delete(plan_to_delete)
                    session.commit()
                    reply = f"Plan with ID {plan_id} has been deleted."
                else:
                    # If the plan is not found, inform the user
                    reply = f"No plan found with ID {plan_id}."
            
            self.bot.reply_to(message, reply)
        
        except ValueError:
            # If the input cannot be converted to an integer, inform the user
            self.bot.reply_to(message, "Invalid plan ID. Please enter a numerical ID.")
        
        except Exception as e:
            logging.error(f"Error in process_delete_plan: {e}")
            self.bot.reply_to(message, "An unexpected error occurred while attempting to delete the plan.")

    def delete_plan_by_id(self, message, plan_id):
        try:
            with self.get_db_session() as session:
                # Look up the plan by ID and delete it
                plan_to_delete = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
                if plan_to_delete:
                    session.delete(plan_to_delete)
                    session.commit()
                    reply = f"Plan '{plan_to_delete.name}' has been deleted."
                else:
                    reply = "Plan not found."
            self.bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=reply)
        except Exception as e:
            logging.error(f"Error in delete_plan_by_id: {e}")
            self.bot.answer_callback_query(message.id, "An error occurred while attempting to delete the plan.")

#########################################
#########################################
################HANDLERS#################
#########################################
#########################################

    # Register handlers
    def setup_handlers(self):
        # Welcome message
        @self.bot.message_handler(commands=['start'])
        def handle_start(message):
            self.send_welcome(message)

        @self.bot.message_handler(content_types=['photo'])
        def handle_photo(message):
            self.handle_photo(message)  # Assuming this shows available plans

        # Status check
        @self.bot.message_handler(commands=['check_status', 'status'])
        def handle_status(message):
            self.check_status(message)

        # Subscribe
        @self.bot.message_handler(commands=['subscribe'])
        def handle_subscribe(message):
            self.subscribe(message)  # Assuming this shows available plans
        
        @self.bot.message_handler(commands=['generate_code'])  # New handler for generating redemption codes
        def handle_generate_code(message):
            self.generate_redemption_code(message)

        # Redeem code
        @self.bot.message_handler(commands=['redeem'])
        def handle_redeem(message):
            self.redeem_code(message)

        # Admin commands
        @self.bot.message_handler(commands=['add_admin'])
        def handle_add_admin(message):
            self.add_admin_command(message)

        @self.bot.message_handler(commands=['add_plan'])
        def handle_add_plan(message):
            self.add_plan_command(message)

        @self.bot.message_handler(commands=['delete_plan'])
        def handle_delete_plan(message):
            self.delete_plan_command(message)
        
        @self.bot.message_handler(content_types=['text'])
        def handle_text_message(message):
            self.channel_id_check(message)

        # Handle callback queries for payment
        @self.bot.callback_query_handler(func=lambda call: True)
        def handle_callback_query(call):
            if call.data.startswith('subscribe_'):
                self.subscribe_callback(call)
            elif call.data.startswith('pay_online_') or call.data.startswith('pay_direct_'):
                self.payment_method_callback(call)
            elif call.data.startswith('approve_') or call.data.startswith('deny_'):
                self.handle_admin_decision(call)
            # ... (handle other callback queries or provide a default response)
            else:
                self.bot.answer_callback_query(call.id, "Action not recognized.")


        # ... (register other command handlers)


my_bot = Bot()
my_bot.setup_handlers()
my_bot.start_polling()

