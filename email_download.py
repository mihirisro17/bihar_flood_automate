import os
import re
import time
import base64
import logging
import paramiko
from datetime import datetime
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError

# Google API Imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ==========================================
# CONFIGURATION
# ==========================================
REPO_DIR = '/home/sac/Documents/python_script/bihar_flood_automate' 
OPERATION_FILE = os.path.join(REPO_DIR, 'operation.txt')
ZIP_DIR = REPO_DIR # Downloading and uploading from the repo root as per your config

# SFTP/SCP Settings
SFTP_HOST = '192.168.2.137'
SFTP_PORT = 22
SFTP_USER = 'sac'
SFTP_PASS = 'sac@123'    # <-- UPDATE THIS
SFTP_REMOTE_DIR = '/home/sac/Documents/new_bihar/bihar_flood_Zip/'

# Loop interval in minutes
INTERVAL_MINUTES = 15

# Gmail API Scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
TOKEN_PATH = os.path.join(REPO_DIR, 'token.json')
CREDS_PATH = os.path.join(REPO_DIR, 'credentials.json')

# ==========================================
# LOGGING MODULE CONFIGURATION
# ==========================================
# Fulfilling TODO: Added FileHandler to save logs to a file alongside console output
log_file_path = os.path.join(REPO_DIR, 'automation.log')

logging.basicConfig(
    level=logging.INFO, # Set to INFO in production
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(log_file_path),  # Save to file
        logging.StreamHandler()              # Print to terminal
    ]
)
logger = logging.getLogger("BiharFloodAuto")

# ==========================================
# PIPELINE FUNCTIONS
# ==========================================

def run_git_pull(repo_dir: str = REPO_DIR) -> bool:
    """Executes a git pull operation using GitPython and restores missing .zip files."""
    logger.info("Executing 'git pull' to check for updates...")
    state_changed = False
    
    try:
        repo = Repo(repo_dir)
        
        if repo.bare:
            logger.error(f"Repository at {repo_dir} is bare. Cannot perform pull.")
            return False

        origin = repo.remotes.origin
        old_commit = repo.head.commit

        logger.debug(f"Pulling from remote: {origin.url}...")
        origin.pull()
        new_commit = repo.head.commit

        if old_commit == new_commit:
            logger.info("Repository is already up to date.")
        else:
            logger.info(f"Git pull downloaded new changes. HEAD moved from {old_commit.hexsha[:7]} to {new_commit.hexsha[:7]}.")
            state_changed = True

        # --- Check for and restore missing .zip files ---
        missing_zips = []
        for diff in repo.index.diff(None):
            if diff.change_type == 'D' and diff.a_path.endswith('.zip'):
                missing_zips.append(diff.a_path)

        if missing_zips:
            logger.warning(f"Detected {len(missing_zips)} missing .zip file(s) that exist in the repository:")
            for zip_file in missing_zips:
                logger.info(f" -> Restoring missing file: {zip_file}")
                repo.git.checkout('--', zip_file)
            
            logger.info("All missing .zip files have been successfully restored.")
            state_changed = True
        else:
            logger.debug("No locally tracked .zip files are missing.")

        return state_changed

    except InvalidGitRepositoryError:
        logger.critical(f"The directory '{repo_dir}' is not a valid git repository.")
    except GitCommandError as e:
        logger.error(f"Git pull failed with status code {e.status}.")
        logger.debug(f"Git error stderr: {e.stderr.strip()}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during git operations: {e}")
        
    return False


def check_operation_status():
    """Reads operation.txt to determine if file copying should run."""
    if not os.path.exists(OPERATION_FILE):
        logger.warning(f"[-] {OPERATION_FILE} not found. Defaulting to 'off'.")
        return False

    with open(OPERATION_FILE, 'r') as file:
        status = file.read().strip().lower()

    return status == 'on'


def fetch_zips_via_api():
    """Fetches unread .zip files from Gmail, cleans filenames, and marks emails as read."""
    os.makedirs(ZIP_DIR, exist_ok=True)
    creds = None
    
    # 1. Authenticate
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            # creds = flow.run_console() # Using console for headless servers
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    # 2. Connect and Search
    try:
        service = build('gmail', 'v1', credentials=creds)
        logger.info("Searching Gmail for UNREAD emails with 'Inundation Probability'...")
        
        results = service.users().messages().list(userId='me', q='subject:"Inundation Probability" is:unread').execute()
        messages = results.get('messages', [])

        if not messages:
            logger.info("No new matching emails found in Gmail.")
            return

        subject_pattern = re.compile(
            r"inundation probability for \d{2}-\d{2}-\d{4} and \d{2}-\d{2}-\d{4}", 
            re.IGNORECASE
        )

        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
            payload = msg_data.get('payload', {})
            headers = payload.get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "")

            if subject_pattern.search(subject):
                logger.info(f"[MATCH] Found email with Subject: '{subject}'")
                parts = payload.get('parts', [])
                attachments_found = 0
                
                for part in parts:
                    filename = part.get('filename')
                    if filename and filename.endswith('.zip'):
                        attachments_found += 1
                        # Clean filename (e.g., "08102025 (1).zip" -> "08102025.zip")
                        clean_filename = re.sub(r'\s*\(\d+\)', '', filename)
                        
                        logger.info(f"   -> Downloading: {filename} (Saving as {clean_filename})")
                        attachment_id = part['body'].get('attachmentId')
                        attachment = service.users().messages().attachments().get(
                            userId='me', messageId=msg['id'], id=attachment_id
                        ).execute()
                        
                        file_data = base64.urlsafe_b64decode(attachment['data'])
                        file_path = os.path.join(ZIP_DIR, clean_filename)
                        
                        with open(file_path, 'wb') as f:
                            f.write(file_data)
                        logger.info(f"   -> Saved successfully to {file_path}")
                
                # Mark as read so it doesn't process again next loop
                service.users().messages().modify(
                    userId='me', id=msg['id'], body={'removeLabelIds': ['UNREAD']}
                ).execute()
                logger.info("   -> Marked email as read.")
            else:
                logger.debug(f"[IGNORED] Subject didn't match full regex pattern: '{subject}'")

    except Exception as e:
        logger.exception(f"An error occurred while interacting with Gmail API: {e}")


def upload_new_zips():
    """Finds zip files and securely copies only the ones missing from the server."""
    if not os.path.exists(ZIP_DIR):
        logger.info(f"ZIP dir not found. Exiting the execution phase.")
        return

    zip_files = [f for f in os.listdir(ZIP_DIR) if f.endswith('.zip')]
    if not zip_files:
        logger.info("No .zip files found to upload.")
        return

    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)

        try:
            remote_files = sftp.listdir(SFTP_REMOTE_DIR)
        except IOError:
            logger.info(f"[-] Remote directory {SFTP_REMOTE_DIR} not found. Creating it...")
            sftp.mkdir(SFTP_REMOTE_DIR)
            remote_files = []

        new_uploads_count = 0
        for zip_name in zip_files:
            if zip_name in remote_files:
                continue 
                
            local_path = os.path.join(ZIP_DIR, zip_name)
            remote_path = f"{SFTP_REMOTE_DIR.rstrip('/')}/{zip_name}"
            
            logger.info(f"[+] Copying new file: {zip_name} to server...")
            sftp.put(local_path, remote_path)
            new_uploads_count += 1
            
        if new_uploads_count > 0:
            logger.info(f"[+] Successfully copied {new_uploads_count} new file(s).")
        else:
            logger.info("[*] All zip files are already on the server.")

        sftp.close()
        transport.close()
        
    except paramiko.AuthenticationException:
        logger.error("[-] Authentication failed. Check your SFTP password.")
    except Exception as e:
        logger.error(f"[-] SFTP Copy failed: {e}")


# ==========================================
# MAIN EXECUTION LOOP
# ==========================================
def main():
    logger.info(f"=== Started Bihar Flood Automation Loop (Checking every {INTERVAL_MINUTES} minutes) ===")
    
    while True:
        try:
            # 1. ALWAYS pull first so we get the latest operation.txt from GitHub
            logger.info("Phase 1: [STARTED] Git pull and recovery")
            run_git_pull()
            logger.info("Phase 1: [ENDED] Git pull and recovery")
            
            logger.info("Phase 2: [STARTED] Command detection")
            op_status = check_operation_status()
            logger.info("Phase 2: [ENDED] Command detection")
            
            # 2. THEN check if the file says 'on' or 'off'
            if op_status:
                logger.info("Phase 3: [STARTED] Fetching Emails")
                fetch_zips_via_api()
                logger.info("Phase 3: [ENDED] Fetching Emails")

                logger.info("Phase 4: [STARTED] SFTP Execution")
                upload_new_zips()
                logger.info("Phase 4: [ENDED] SFTP Execution")
            else:
                logger.info("[*] Operation is OFF. Skipping Email Fetch and SFTP copy.")
                
        except Exception as e:
            logger.error(f"[-] Unexpected error in loop: {e}")
            
        # Wait for interval before checking again
        logger.info(f"Sleeping for {INTERVAL_MINUTES} minutes...")
        time.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    main()