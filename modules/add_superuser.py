from models import Admin, Base, engine, Session

# Replace with your actual details
SUPERUSER_ID =  123456 # Your Telegram user ID
USERNAME = ''
FIRST_NAME = ''
LAST_NAME = ''

# Create the session and add the superuser
with Session() as session:
    superuser = Admin(
        admin_id=SUPERUSER_ID,
        username=USERNAME,
        first_name=FIRST_NAME,
        last_name=LAST_NAME,
        is_superuser=True
    )
    session.add(superuser)
    session.commit()
