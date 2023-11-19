from models import Admin, Base, engine, Session

# Replace with your actual details
SUPERUSER_ID =  89779164 # Your Telegram user ID
USERNAME = 'aaghania'
FIRST_NAME = 'Arman'
LAST_NAME = 'Aghania'

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
