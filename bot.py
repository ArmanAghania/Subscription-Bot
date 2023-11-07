import logging
import telebot
from telebot import types
from modules.models import session, User, Subscription, Admin, Payment, Code, Session, SubscriptionPlan, Base
from decimal import Decimal
from datetime import datetime, timedelta
import requests
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from contextlib import contextmanager


logging.basicConfig(level=logging.INFO)

TOKEN = ''

class Bot:
    def __init__(self, 
                 bot=telebot.TeleBot(token=TOKEN),
                #  menu=MainMenu(), 
                 db_uri=''):
        self.bot = bot
        self.engine = create_engine(db_uri, echo=True, pool_size=10, max_overflow=20)
        self.SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=self.engine))
        Base.metadata.create_all(bind=self.engine)

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

    def start_polling(self):
        self.bot.polling()

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

        # Retrieve the selected plan details from the database
        with Session() as session:
            selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
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

    def payment_method_callback(self, call):
        try:
            logging.info(f"Callback data received: {call.data}")
            parts = call.data.split('_')
            print(parts)

            chat_id = call.message.chat.id
            payment_method = parts[0] + '_' + parts[1]  # This will be 'direct_payment'
            plan_id = int(parts[2])  # This extracts the plan ID correctly

            logging.info(f"Payment method: {payment_method}, Plan ID: {plan_id}")

            if payment_method == 'pay_online':
                # Handle online payment
                logging.info("Handling online payment...")
                # Add online payment handling code here
            elif payment_method == 'direct_payment':
                # Handle direct payment
                self.bot.send_message(chat_id, "To complete your subscription via direct payment, please transfer the payment to 6219861927644152 and provide us with the receipt Image.")
                logging.info("Sent direct payment instructions")
            else:
                logging.error("Unrecognized payment method.")

            # Answer the callback query
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logging.error(f"Error in payment_method_callback: {e}")
            # It's important to answer the callback query even in case of errors
            self.bot.answer_callback_query(call.id)

    def subscribe_callback(self, call):
        chat_id = call.message.chat.id
        plan_id = int(call.data.split('_')[1])  # This extracts the plan ID from the callback data

        # Retrieve the selected plan details from the database
        with Session() as session:
            selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
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

    def is_admin(self, user_id):
        try:
            with Session() as session:
                admin = session.query(Admin).filter_by(admin_id=user_id).first()
                return admin is not None
        except Exception as e:
            # Log the error and handle it appropriately
            print(f"An error occurred: {e}")
            return False  # Default to False in case of an error
        
    def handle_direct_payment(self, message):
        chat_id = message.chat.id
        # Inform the user about the direct payment process

        with Session() as session:
            # Assume you already have the selected plan's ID and details
            plan_id = self.get_plan_id_from_user_choice(chat_id)
            selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
            if selected_plan:
                # Create a new payment record
                new_payment = Payment(
                    user_id=chat_id,
                    subscription_id=selected_plan.subscription_id, # Assuming you have a subscription_id in your SubscriptionPlan model
                    amount=selected_plan.price,  # Assuming the SubscriptionPlan model has a price field
                    payment_method='direct',
                    payment_status='pending',
                    payment_date=datetime.utcnow()
                    # Add any other fields you need
                )
                session.add(new_payment)
                session.commit()
                # After committing, you can access new_payment.payment_id if you need it for any reason
            else:
                self.bot.send_message(chat_id, "The selected plan does not exist.")
        
        self.bot.send_message(chat_id, "To complete your subscription via direct payment, please transfer the payment to 6219861927644152 and provide us with the receipt number.")
    
    def handle_messages(self, message):
        chat_id = message.chat.id
        if message.content_type == 'photo':
            # Assume the photo is the receipt. Forward it to the admins.
            with Session() as session:
                payment = session.query(Payment).filter_by(user_id=chat_id).first()
                admins = session.query(Admin).all()
                user = session.query(User).filter_by(user_id=chat_id).first()
                user_details = f"{user.first_name} {user.last_name} ({user.user_id})" if user else "Unknown User"
                
                for admin in admins:
                    # Forward the photo to each admin
                    self.bot.forward_message(admin.admin_id, chat_id, message.message_id)
                    # Send the inline buttons for approval or denial to each admin with user details
                    approval_message = self.bot.send_message(admin.admin_id, f"Please approve or deny the payment for {user_details}:")
                    markup = self.generate_admin_approval_markup(chat_id, approval_message.message_id, payment.id)
                    self.bot.edit_message_text(chat_id=admin.admin_id, message_id=approval_message.message_id, text=f"Please approve or deny the payment for {user_details}:", reply_markup=markup)

                    # approval_message = self.bot.send_message(admin.admin_id, f"Please approve or deny the payment for {user_details}:", reply_markup=self.generate_admin_approval_markup(chat_id, message.message_id))
                    logging.info(f"Admin approval message sent with message_id: {approval_message.message_id}")                    
                    # Store the message_id of the approval message to edit later
                    if payment:
                        payment.receipt_message_id = message.message_id
                        session.commit()
        elif message.text and message.text.startswith('Receipt:'):
            # This is where you would handle text-based receipts if necessary
            # For example, you could extract the receipt number and store it for admin review
            receipt_number = message.text.split(':')[1].strip()  # This is just an example
            # Here you would store the receipt number in your database and notify the admins
            # For now, I'll just print it for demonstration purposes
            print(f"Received text-based receipt: {receipt_number}")
            # You should replace this with actual database storage and admin notification logic
        else:
            # Handle other text messages here
            # For example, you can handle commands or other user inputs that are not receipt confirmations
            pass

    def generate_admin_approval_markup(self, user_id, payment_id):
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("Approve", callback_data=f"approve_{user_id}_{payment_id}"),
            types.InlineKeyboardButton("Deny", callback_data=f"deny_{user_id}_{payment_id}")
        )
        logging.info(f"Generated callback data with admin_approval_message_id: {payment_id}")
        return markup

    def handle_admin_decision(self, call):
        admin_id = call.from_user.id
        user_id, message_id = map(int, call.data.split('_')[1:])
        decision = call.data.split('_')[0]

        with Session() as session:
            user = session.query(User).filter_by(user_id=user_id).first()
            if not user:
                self.bot.send_message(admin_id, "The user does not exist in the database.")
                self.bot.answer_callback_query(call.id)
                return

            payment = session.query(Payment).filter_by(user_id=user_id).first()
            if not payment:
                self.bot.send_message(admin_id, "Payment information not found.")
                self.bot.answer_callback_query(call.id)
                return

            selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=payment.plan_id).first()
            if not selected_plan:
                self.bot.send_message(admin_id, "Subscription plan not found.")
                self.bot.answer_callback_query(call.id)
                return

            if decision == 'approve':
                # Approve payment and update subscription
                payment.payment_status = 'confirmed'
                # Check and update user's subscription status
                user.subscription_status = 'active'
                if user.subscription_expiry and user.subscription_expiry > datetime.utcnow():
                    user.subscription_expiry += timedelta(days=selected_plan.duration_days)
                else:
                    user.subscription_expiry = datetime.utcnow() + timedelta(days=selected_plan.duration_days)
                session.commit()
                # Inform user and admin
                self.bot.send_message(user_id, "Your payment has been approved, and your subscription is now active.")
                self.bot.send_message(admin_id, f"Payment approved for user_id: {user_id}.")
            elif decision == 'deny':
                # Deny payment
                payment.payment_status = 'denied'
                session.commit()
                # Inform user and admin
                self.bot.send_message(user_id, "Your payment was not accepted. Please contact support for more information.")
                self.bot.send_message(admin_id, f"Payment denied for user_id: {user_id}.")

        self.bot.answer_callback_query(call.id)

    def confirm_payment(self, message):
        if self.is_admin(message.from_user.id):
            try:
                command_parts = message.text.split()
                user_id = int(command_parts[1])
                receipt = command_parts[2]

                # Here you would update the payment status in the database and the user's subscription
                with Session() as session:
                    # Let's assume the Payment model has a receipt field
                    payment = session.query(Payment).filter_by(receipt=receipt).first()
                    if payment:
                        payment.payment_status = 'confirmed'
                        # Also update user's subscription status if needed
                        # ...
                        session.commit()
                        self.bot.send_message(user_id, "Your payment has been confirmed, and your subscription is now active.")
                        self.bot.send_message(message.chat.id, "Payment confirmed for user_id: {}".format(user_id))
                    else:
                        self.bot.send_message(message.chat.id, "No payment found with that receipt.")
            except IndexError:
                self.bot.send_message(message.chat.id, "Usage: /confirm_payment <user_id> <receipt>")
            except ValueError:
                self.bot.send_message(message.chat.id, "Invalid user ID or receipt.")
            except Exception as e:
                self.bot.send_message(message.chat.id, f"An error occurred: {e}")

    def redeem_code(self, message):
        chat_id = message.chat.id
        # Send a message to ask for the code
        sent = self.bot.reply_to(message, "Please enter your redemption code.")
        self.bot.register_next_step_handler(sent, self.process_redeem_code)

    def process_redeem_code(self, message):
        chat_id = message.chat.id
        code_text = message.text
        # Validate the code
        code = session.query(Code).filter_by(code=code_text, used_status=False).first()
        if code:
            # Apply the code to the user's subscription
            # This is where you would extend the subscription based on the code's value
            # For now, let's just mark the code as used
            code.used_status = True
            session.commit()
            reply = "Your code has been redeemed successfully."
        else:
            reply = "The code is invalid or has already been used."
        self.bot.send_message(chat_id, reply)

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

    # Register handlers
    def setup_handlers(self):
        # Welcome message
        @self.bot.message_handler(commands=['start'])
        def handle_start(message):
            self.send_welcome(message)

        # Status check
        @self.bot.message_handler(commands=['check_status', 'status'])
        def handle_status(message):
            self.check_status(message)

        # Subscribe
        @self.bot.message_handler(commands=['subscribe'])
        def handle_subscribe(message):
            self.subscribe(message)

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

        @self.bot.message_handler(commands=['confirm_payment'])
        def handle_confirm_payment(message):
            self.confirm_payment(message)

        # ... (register other command handlers)

        # Handle callback queries for payment
        @self.bot.callback_query_handler(func=lambda call: True)
        def handle_callback_query(call):
            # Here you can split the logic based on call.data
            if call.data.startswith('subscribe_'):
                self.callback_query(call)
            elif call.data.startswith('pay_online_') or call.data.startswith('direct_payment_'):
                self.payment_method_callback(call)
            elif call.data.startswith('approve_') or call.data.startswith('deny_'):
                self.handle_admin_decision(call)
            elif call.data.startswith('delete_plan_'):
                plan_id = int(call.data.split('_')[1])
                self.delete_plan_by_id(call.message, plan_id)
            else:
                # Handle other callback queries or provide a default response
                self.bot.answer_callback_query(call.id, "Action not recognized.")

        def handle_text_and_photo(message):
            self.handle_messages(message)

        @self.bot.message_handler(content_types=['photo'])
        def handle_photo(message):
            self.handle_messages(message)
    


# Replace 'YOUR_BOT_TOKEN' with your bot's actual token
# TOKEN = '6871745287:AAF5LBcUnqSnW_cu9JJrqfDaSzFqlm9_QBc'
# bot = telebot.TeleBot(bot_token)


# Handlers for the bot commands
# @bot.message_handler(commands=['start'])
# def send_welcome(message):
#     # Extract user data from the message
#     user_id = message.from_user.id
#     first_name = message.from_user.first_name
#     last_name = message.from_user.last_name
#     username = message.from_user.username  # Some users might not have a username

#     # Start a new database session
#     with Session() as session:
#         # Check if the user already exists in the database
#         existing_user = session.query(User).filter_by(user_id=user_id).first()

#         if existing_user:
#             reply = f"Welcome back {existing_user.first_name}! Use /subscribe to manage your subscription or /status to check your current subscription status."
#         else:
#             # Create a new user in the database
#             new_user = User(
#                 user_id=user_id,
#                 username=username,
#                 first_name=first_name,
#                 last_name=last_name,
#                 subscription_status='inactive',
#                 # Set the subscription_expiry to None or a default value as needed
#             )
#             session.add(new_user)
#             session.commit()
#             reply = "Welcome to the Subscription Manager Bot! You have been registered. Use /subscribe to choose a subscription plan."

#         # Send the welcome message
#         bot.reply_to(message, reply)

# @bot.message_handler(commands=['check_status'])
# def check_status(message):
#     bot.reply_to(message, "Status command received.")

# @bot.message_handler(commands=['status'])
# def check_status(message):
#     chat_id = message.chat.id
#     print(f"Received /status command from {chat_id}.")  # Debug print
#     try:
#         print("Attempting to create a session...")  # Debug print
#         with Session() as session:
#             print("Session created, querying the user...")  # Debug print
#             user = session.query(User).filter_by(user_id=chat_id).first()
#             if user:
#                 if user.subscription_status == 'active':
#                     expiry = user.subscription_expiry.strftime("%Y-%m-%d %H:%M:%S") if user.subscription_expiry else "an unknown time"
#                     reply = f"Your subscription is active until {expiry}."
#                 else:
#                     reply = "You do not have an active subscription."
#             else:
#                 reply = "You are not registered in our database."
#             print(f"Replying with: {reply}")  # Debug print
#         bot.reply_to(message, reply)
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         bot.reply_to(message, "An error occurred while checking your status.")

# @bot.message_handler(commands=['subscribe'])
# def subscribe(message):
#     chat_id = message.chat.id
#     with Session() as session:
#         plans = session.query(SubscriptionPlan).all()
#         if plans:
#             markup = types.InlineKeyboardMarkup()
#             for plan in plans:
#                 button_text = f"{plan.name} - ${plan.price} for {plan.duration_days} days"
#                 markup.add(types.InlineKeyboardButton(button_text, callback_data=f"subscribe_{plan.plan_id}"))
#             bot.send_message(chat_id, "Please choose a subscription plan:", reply_markup=markup)
#         else:
#             bot.send_message(chat_id, "There are currently no subscription plans available.")

# @bot.callback_query_handler(func=lambda call: call.data.startswith('subscribe_'))
# def callback_query(call):
#     chat_id = call.message.chat.id
#     plan_id = int(call.data.split('_')[1])  # This extracts the plan ID from the callback data

#     # Retrieve the selected plan details from the database
#     with Session() as session:
#         selected_plan = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
#         if selected_plan:
#             # Proceed to payment method selection
#             markup = types.InlineKeyboardMarkup()
#             # Assuming you have two payment methods: 'online' and 'direct'
#             markup.add(types.InlineKeyboardButton("Pay Online", callback_data=f"pay_online_{plan_id}"))
#             markup.add(types.InlineKeyboardButton("Direct Payment", callback_data=f"direct_payment_{plan_id}"))
#             bot.send_message(chat_id, f"You have selected the {selected_plan.name} plan. Please choose your payment method:", reply_markup=markup)
#         else:
#             bot.send_message(chat_id, "The selected plan does not exist.")

#     # Make sure to answer the callback query
#     bot.answer_callback_query(call.id)

# def generate_admin_approval_markup(user_id, message_id):
#     markup = types.InlineKeyboardMarkup()
#     markup.row(
#         types.InlineKeyboardButton("Approve", callback_data=f"approve_{user_id}_{message_id}"),
#         types.InlineKeyboardButton("Deny", callback_data=f"deny_{user_id}_{message_id}")
#     )
#     return markup



# Additional callback query handler for payment method selection
# @bot.callback_query_handler(func=lambda call: call.data.startswith('pay_online_') or call.data.startswith('direct_payment_'))
# def payment_method_callback(call):
#     try:
#         logging.info(f"Callback data received: {call.data}")
#         chat_id = call.message.chat.id
#         plan_id = int(call.data.split('_')[2])
#         payment_method = call.data.split('_')[0]

#         logging.info(f"Payment method: {payment_method}, Plan ID: {plan_id}")

#         # Since the callback data is something like "direct_payment_1", we split it and check the first part.
#         if 'pay_online' in call.data:
#             # Handle online payment
#             logging.info("Handling online payment...")
#             # Add online payment handling code here
#         elif 'direct_payment' in call.data:
#             # Handle direct payment
#             bot.send_message(chat_id, "To complete your subscription via direct payment, please transfer the payment to [Bank Account Details] and provide us with the receipt number.")
#             logging.info("Sent direct payment instructions")
#         else:
#             logging.error("Unrecognized payment method.")

#         # Answer the callback query
#         bot.answer_callback_query(call.id)
#     except Exception as e:
#         logging.error(f"Error in payment_method_callback: {e}")
#         # It's important to answer the callback query even in case of errors
#         bot.answer_callback_query(call.id)


# def is_admin(user_id):
#     try:
#         with Session() as session:
#             admin = session.query(Admin).filter_by(admin_id=user_id).first()
#             return admin is not None
#     except Exception as e:
#         # Log the error and handle it appropriately
#         print(f"An error occurred: {e}")
#         return False  # Default to False in case of an error

# @bot.message_handler(commands=['direct_payment'])
# def handle_direct_payment(message):
#     chat_id = message.chat.id
#     # Inform the user about the direct payment process
#     bot.send_message(chat_id, "To complete your subscription via direct payment, please transfer the payment to 6219861927644152 and provide us with the receipt number.")

# @bot.message_handler(content_types=['text', 'photo'])
# def handle_messages(message):
#     chat_id = message.chat.id
#     if message.content_type == 'photo':
#         # Assume the photo is the receipt. Forward it to the admins.
#         with Session() as session:
#             admins = session.query(Admin).all()
#             for admin in admins:
#                 # Forward the photo to each admin
#                 bot.forward_message(admin.admin_id, chat_id, message.message_id)
#                 # Send the inline buttons for approval or denial to each admin
#                 bot.send_message(admin.admin_id, "Please approve or deny the payment:",
#                                  reply_markup=generate_admin_approval_markup(chat_id, message.message_id))
#     elif message.text and message.text.startswith('Receipt:'):
#         # This is where you would handle text-based receipts if necessary
#         # For example, you could extract the receipt number and store it for admin review
#         receipt_number = message.text.split(':')[1].strip()  # This is just an example
#         # Here you would store the receipt number in your database and notify the admins
#         # For now, I'll just print it for demonstration purposes
#         print(f"Received text-based receipt: {receipt_number}")
#         # You should replace this with actual database storage and admin notification logic
#     else:
#         # Handle other text messages here
#         # For example, you can handle commands or other user inputs that are not receipt confirmations
#         pass

# @bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('deny_'))
# def handle_admin_decision(call):
#     admin_id = call.from_user.id
#     user_id, message_id = map(int, call.data.split('_')[1:])
#     decision = call.data.split('_')[0]

#     with Session() as session:
#         user = session.query(User).filter_by(user_id=user_id).first()
#         if not user:
#             # If the user isn't found, send an error message to the admin
#             bot.send_message(admin_id, "The user does not exist in the database.")
#             bot.answer_callback_query(call.id)
#             return

#         if decision == 'approve':
#             # Here you would update the user's subscription based on your business logic
#             if user.subscription_status != 'active':
#                 # For example, add the subscription duration to the user's account
#                 user.subscription_status = 'active'
#                 user.subscription_expiry = datetime.datetime.utcnow() + datetime.timedelta(days=30)  # Example for 30 days
#                 session.commit()
#                 bot.send_message(user_id, "Your payment has been approved, and your subscription is now active.")
#                 bot.send_message(admin_id, f"Payment approved for user_id: {user_id}.")
#             else:
#                 # If the subscription is already active, inform the admin
#                 bot.send_message(admin_id, f"The user's subscription is already active.")
#         elif decision == 'deny':
#             # Here you would handle the payment denial
#             # For example, you could log the denial and notify the user
#             bot.send_message(user_id, f"Your payment was not accepted. For more information, you can contact: @{call.from_user.username}")
#             bot.send_message(admin_id, f"Payment denied for user_id: {user_id}.")

#     # Answer the callback query to prevent the loading animation on the button
#     bot.answer_callback_query(call.id)

# @bot.message_handler(commands=['confirm_payment'])
# def confirm_payment(message):
#     if is_admin(message.from_user.id):
#         try:
#             command_parts = message.text.split()
#             user_id = int(command_parts[1])
#             receipt = command_parts[2]

#             # Here you would update the payment status in the database and the user's subscription
#             with Session() as session:
#                 # Let's assume the Payment model has a receipt field
#                 payment = session.query(Payment).filter_by(receipt=receipt).first()
#                 if payment:
#                     payment.payment_status = 'confirmed'
#                     # Also update user's subscription status if needed
#                     # ...
#                     session.commit()
#                     bot.send_message(user_id, "Your payment has been confirmed, and your subscription is now active.")
#                     bot.send_message(message.chat.id, "Payment confirmed for user_id: {}".format(user_id))
#                 else:
#                     bot.send_message(message.chat.id, "No payment found with that receipt.")
#         except IndexError:
#             bot.send_message(message.chat.id, "Usage: /confirm_payment <user_id> <receipt>")
#         except ValueError:
#             bot.send_message(message.chat.id, "Invalid user ID or receipt.")
#         except Exception as e:
#             bot.send_message(message.chat.id, f"An error occurred: {e}")






# @bot.message_handler(commands=['redeem'])
# def redeem_code(message):
#     chat_id = message.chat.id
#     # Send a message to ask for the code
#     sent = bot.reply_to(message, "Please enter your redemption code.")
#     bot.register_next_step_handler(sent, process_redeem_code)

# def process_redeem_code(message):
#     chat_id = message.chat.id
#     code_text = message.text
#     # Validate the code
#     code = session.query(Code).filter_by(code=code_text, used_status=False).first()
#     if code:
#         # Apply the code to the user's subscription
#         # This is where you would extend the subscription based on the code's value
#         # For now, let's just mark the code as used
#         code.used_status = True
#         session.commit()
#         reply = "Your code has been redeemed successfully."
#     else:
#         reply = "The code is invalid or has already been used."
#     bot.send_message(chat_id, reply)

# Admin-only commands
# @bot.message_handler(commands=['add_admin'])
# def add_admin_command(message):
#     chat_id = message.chat.id
#     # Check if the user is a superuser
#     admin = session.query(Admin).filter_by(admin_id=chat_id, is_superuser=True).first()
#     if admin:
#         # Provide instructions on how to add an admin
#         reply = "Please send the user ID of the person you want to make an admin."
#         # Proceed with the next step of adding an admin
#     else:
#         reply = "You do not have permission to add admins."
#     bot.reply_to(message, reply)


# @bot.message_handler(commands=['approve_admin'])
# def approve_admin_command(message):
#     bot.reply_to(message, "Superuser is approving an admin application...")

# @bot.message_handler(commands=['deny_admin'])
# def deny_admin_command(message):
#     bot.reply_to(message, "Superuser is denying an admin application...")

# @bot.message_handler(commands=['generate_code'])
# def generate_code_command(message):
#     bot.reply_to(message, "Generating a new code...")

# @bot.message_handler(commands=['send_message'])
# def send_mass_message_command(message):
#     bot.reply_to(message, "Sending a personalized mass message to users...")

# def is_admin(user_id):
#     with Session() as session:
#         # Query the database for the admin entry
#         admin = session.query(Admin).filter_by(admin_id=user_id).first()
#         # Check if the admin exists and if they are flagged as a superuser
#         return admin is not None and admin.is_superuser
    
# @bot.message_handler(commands=['add_plan'])
# def add_plan_command(message):
#     if is_admin(message.from_user.id):
#         try:
#             msg = bot.reply_to(message, "Enter the new plan details in the format: name, price, duration_days")
#             bot.register_next_step_handler(msg, process_add_plan)
#         except Exception as e:
#             logging.error(f"Error in add_plan_command: {e}")
#             bot.reply_to(message, "An error occurred while processing your request.")
#     else:
#         bot.reply_to(message, "You are not authorized to add plans.")

# def process_add_plan(message):
#     try:
#         plan_data = message.text.split(',')
#         if len(plan_data) != 3:
#             raise ValueError("Incorrect number of parameters for a new plan.")
#         name = plan_data[0].strip()
#         price = Decimal(plan_data[1].strip())
#         duration_days = int(plan_data[2].strip())

#         # Rest of your code for adding a new plan
#     except (IndexError, ValueError) as e:
#         logging.error(f"Error in process_add_plan: {e}")
#         bot.reply_to(message, "Incorrect plan format. Please send the data in the format: name, price, duration_days.")
#     except Exception as e:
#         logging.error(f"Unexpected error in process_add_plan: {e}")
#         bot.reply_to(message, "An unexpected error occurred.")

# @bot.message_handler(commands=['delete_plan'])
# def delete_plan_command(message):
#     if is_admin(message.from_user.id):
#         # Send a message asking for the identifier of the plan to delete
#         msg = bot.reply_to(message, "Enter the ID of the plan you wish to delete:")
#         bot.register_next_step_handler(msg, process_delete_plan)
#     else:
#         bot.reply_to(message, "You are not authorized to delete plans.")

# def process_delete_plan(message):
#     try:
#         # Assuming the plan ID is an integer
#         plan_id = int(message.text.strip())
        
#         with Session() as session:
#             # Look up the plan by ID
#             plan_to_delete = session.query(SubscriptionPlan).filter_by(plan_id=plan_id).first()
#             if plan_to_delete:
#                 # Delete the plan from the database
#                 session.delete(plan_to_delete)
#                 session.commit()
#                 reply = f"Plan with ID {plan_id} has been deleted."
#             else:
#                 # If the plan is not found, inform the user
#                 reply = f"No plan found with ID {plan_id}."
        
#         bot.reply_to(message, reply)
    
#     except ValueError:
#         # If the input cannot be converted to an integer, inform the user
#         bot.reply_to(message, "Invalid plan ID. Please enter a numerical ID.")
    
#     except Exception as e:
#         logging.error(f"Error in process_delete_plan: {e}")
#         bot.reply_to(message, "An unexpected error occurred while attempting to delete the plan.")

# Polling
# while True:
#     try:
#         bot.polling(none_stop=True)
#     except Exception as e:
#         logging.error(f"Bot polling failed: {e}")
#         bot.stop_polling()
#         time.sleep(10)

my_bot = Bot()
my_bot.setup_handlers()
my_bot.start_polling()
