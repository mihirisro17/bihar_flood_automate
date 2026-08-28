import os
import subprocess
import paramiko

# ==========================================
# CONFIGURATION
# ==========================================
# Automatically use the directory where this script is located
REPO_DIR = os.path.dirname(os.path.abspath(__file__)) 
OPERATION_FILE = os.path.join(REPO_DIR, 'operation.txt')

# Directory containing the zip files pulled from GitHub
ZIP_DIR = os.path.join(REPO_DIR, 'bihar_flood_Zip')

# SFTP Settings
SFTP_HOST = '192.168.2.137'
SFTP_PORT = 22
SFTP_USER = 'sac'
SFTP_PASS = 'sac@123'    # <-- UPDATE THIS
SFTP_REMOTE_DIR = '/home/sac/Documents/new_bihar/bihar_flood_Zip/'
# ==========================================

def check_operation_status():
    """Reads operation.txt to determine if git pull should run."""
    if not os.path.exists(OPERATION_FILE):
        print(f"[-] {OPERATION_FILE} not found. Defaulting to 'off'.")
        return False

    with open(OPERATION_FILE, 'r') as file:
        status = file.read().strip().lower()

    if status == 'on':
        return True
    elif status == 'off':
        return False
    else:
        print(f"[-] Invalid status '{status}'. Expected 'on' or 'off'.")
        return False

def run_git_pull():
    """Executes a git pull command in the repository directory."""
    print(f"[+] Executing 'git pull' in {REPO_DIR}...")
    try:
        result = subprocess.run(
            ['git', 'pull'], 
            cwd=REPO_DIR, 
            check=True, 
            text=True, 
            capture_output=True
        )
        print(result.stdout)
        print("[+] Git pull completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[-] Git pull failed:\n{e.stderr}")
    except FileNotFoundError:
        print("[-] Error: Git is not installed or not found in system path.")

def upload_zips_to_sftp():
    """Finds all zip files in the ZIP_DIR and uploads them via SFTP."""
    if not os.path.exists(ZIP_DIR):
        print(f"[-] Error: Directory not found at {ZIP_DIR}")
        print("[-] Skipping upload.")
        return

    # Find all .zip files in the directory
    zip_files = [f for f in os.listdir(ZIP_DIR) if f.endswith('.zip')]
    
    if not zip_files:
        print(f"[-] No .zip files found in {ZIP_DIR}. Nothing to upload.")
        return

    print(f"[+] Found {len(zip_files)} zip file(s). Connecting to SFTP {SFTP_HOST}...")
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)

        # Upload each zip file found
        for zip_name in zip_files:
            local_path = os.path.join(ZIP_DIR, zip_name)
            remote_path = f"{SFTP_REMOTE_DIR.rstrip('/')}/{zip_name}"
            
            print(f"[+] Uploading {zip_name}...")
            sftp.put(local_path, remote_path)
            
        print("[+] All uploads completed successfully!")

        sftp.close()
        transport.close()
        
    except paramiko.AuthenticationException:
        print("[-] Authentication failed. Check your SFTP password.")
    except Exception as e:
        print(f"[-] SFTP upload failed: {e}")

def main():
    print("=== Starting Bihar Flood Automation ===")
    
    # 1. Read operation.txt and pull if 'on'
    if check_operation_status():
        run_git_pull()
    else:
        print("[*] Operation is OFF. Skipping git pull.")

    # 2. Upload all zip files found in the directory
    upload_zips_to_sftp()
    
    print("=== Process Complete ===")

if __name__ == "__main__":
    main()
