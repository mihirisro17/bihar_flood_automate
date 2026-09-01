# import imaplib
# import email
# from email.header import decode_header
# import re
# import logging

# # Configure logging for testing
# logging.basicConfig(
#     level=logging.INFO,
#     format="[%(asctime)s] [%(levelname)s] %(message)s",
#     datefmt="%H:%M:%S"

# )
# logger = logging.getLogger("GmailTester")

# # --- CREDENTIALS ---
# GMAIL_USER = "mihirisro@gmail.com"
# GMAIL_APP_PASS = "wkkr fuey xroz mzip"  # 16-character App Password
# GMAIL_IMAP_SERVER = "imap.gmail.com"

# def test_gmail_subject_filter():
#     logger.info("Connecting to Gmail...")
    
#     try:
#         mail = imaplib.IMAP4_SSL(GMAIL_IMAP_SERVER)
#         mail.login(GMAIL_USER, GMAIL_APP_PASS)
#         mail.select("INBOX")

#         # 1. Broad IMAP Search
#         # IMAP SEARCH is inherently case-insensitive.
#         # We use 'ALL' instead of 'UNSEEN' so you can test it on emails you have already read.
#         logger.info("Searching for emails with 'Inundation Probability' in the subject...")
#         status, messages = mail.search(None, '(SUBJECT "Inundation Probability")')
        
#         if status != "OK":
#             logger.error("Search failed.")
#             return

#         mail_ids = messages[0].split()
#         if not mail_ids:
#             logger.info("No matching emails found in the inbox.")
#             return
            
#         logger.info(f"Found {len(mail_ids)} potential email(s). Validating exact patterns...")

#         # 2. Strict Python Regex Validation
#         # Matches: "inundation probability for dd-mm-yyyy and dd-mm-yyyy" (Case Insensitive)
#         subject_pattern = re.compile(
#             r"inundation probability for \d{2}-\d{2}-\d{4} and \d{2}-\d{2}-\d{4}", 
#             re.IGNORECASE
#         )

#         valid_emails_found = 0

#         for msg_id in mail_ids:
#             res, data = mail.fetch(msg_id, "(RFC822)")
#             if res != "OK":
#                 continue

#             raw_email = data[0][1]
#             msg = email.message_from_bytes(raw_email)
            
#             # Decode the subject
#             subject, encoding = decode_header(msg.get("Subject"))[0]
#             if isinstance(subject, bytes):
#                 subject = subject.decode(encoding or "utf-8")

#             # Check if it matches the exact date pattern
#             if subject_pattern.search(subject):
#                 valid_emails_found += 1
#                 logger.info(f"[MATCH] Subject: '{subject}'")
                
#                 # Check for attachments in this matched email
#                 attachments = []
#                 for part in msg.walk():
#                     if str(part.get("Content-Disposition")).startswith("attachment"):
#                         filename = part.get_filename()
#                         if filename:
#                             attachments.append(filename)
                
#                 if attachments:
#                     logger.info(f"   -> Attachments found: {attachments}")
#                 else:
#                     logger.warning("   -> No attachments found in this email.")
#             else:
#                 logger.debug(f"[IGNORED] Subject didn't match full pattern: '{subject}'")

#         logger.info(f"Testing complete. Found {valid_emails_found} perfectly matched email(s).")
        
#         mail.close()
#         mail.logout()

#     except Exception as e:
#         logger.exception(f"An error occurred: {e}")

# if __name__ == "__main__":
#     test_gmail_subject_filter()


import os
import re
import base64
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("GmailAPI-Downloader")

# The scope you configured in Google Cloud
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
ZIP_DIR = "./downloaded_zips"

def download_zips_via_api():
    os.makedirs(ZIP_DIR, exist_ok=True)
    creds = None
    
    # 1. Authenticate using OAuth 2.0
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Change to run_console() if running on a headless Linux server via SSH
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0) 
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('gmail', 'v1', credentials=creds)

        # 2. Broad Search (Case-insensitive)
        logger.info("Searching for emails with 'Inundation Probability'...")
        results = service.users().messages().list(userId='me', q='subject:"Inundation Probability"').execute()
        messages = results.get('messages', [])

        if not messages:
            logger.info("No matching emails found.")
            return

        logger.info(f"Found {len(messages)} potential email(s). Validating exact regex pattern...")

        # 3. Strict Python Regex Validation
        subject_pattern = re.compile(
            r"inundation probability for \d{2}-\d{2}-\d{4} and \d{2}-\d{2}-\d{4}", 
            re.IGNORECASE
        )

        valid_emails_found = 0

        # 4. Process each email
        for msg in messages:
            # Fetch email payload
            msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
            payload = msg_data.get('payload', {})
            headers = payload.get('headers', [])
            
            # Extract Subject
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "")

            if subject_pattern.search(subject):
                valid_emails_found += 1
                logger.info(f"[MATCH] Subject: '{subject}'")
                
                # Look for attachments
                parts = payload.get('parts', [])
                attachments_found = 0
                
                for part in parts:
                    filename = part.get('filename')
                    
                    if filename and filename.endswith('.zip'):
                        attachments_found += 1
                        logger.info(f"   -> Downloading: {filename}")
                        
                        # Get the attachment ID
                        attachment_id = part['body'].get('attachmentId')
                        
                        # Fetch the actual file data using the attachment ID
                        attachment = service.users().messages().attachments().get(
                            userId='me', messageId=msg['id'], id=attachment_id
                        ).execute()
                        
                        # Google API encodes files in Base64 URL-safe format
                        file_data = base64.urlsafe_b64decode(attachment['data'])
                        
                        # Save it locally
                        file_path = os.path.join(ZIP_DIR, filename)
                        with open(file_path, 'wb') as f:
                            f.write(file_data)
                            
                        logger.info(f"   -> Saved successfully to {file_path}")
                
                if attachments_found == 0:
                    logger.warning("   -> No .zip attachments found in this matched email.")
            else:
                logger.debug(f"[IGNORED] Subject didn't match full pattern: '{subject}'")

        logger.info(f"Complete. Processed {valid_emails_found} matching email(s).")

    except Exception as e:
        logger.exception(f"An error occurred: {e}")

if __name__ == '__main__':
    download_zips_via_api()