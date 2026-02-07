import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import paramiko

HOST = '168.231.87.2'
USER = 'root'
PASS = 'c00s-ney9-en8u-zhpc-A'

LOCAL_FILE = r'c:\Users\inigo\OneDrive\Documents\Msc. Computer Science\Venture Lab\Venture_Lab\backend\main.py'
REMOTE_FILE = '/root/voice-agent/backend/main.py'

def ssh_run(client, cmd, timeout=60):
    print(f'\n>>> {cmd}')
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    exit_code = stdout.channel.recv_exit_status()
    if out:
        print(out.rstrip())
    if err:
        print(f'[stderr] {err.rstrip()}')
    print(f'[exit_code: {exit_code}]')
    return out, err, exit_code

def main():
    print(f'Connecting to {HOST}...')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=15)
    print('Connected.')

    # Step 1: Upload main.py via SFTP
    print(f'\n=== STEP 1: Upload main.py ===')
    sftp = client.open_sftp()
    sftp.put(LOCAL_FILE, REMOTE_FILE)
    remote_stat = sftp.stat(REMOTE_FILE)
    print(f'Uploaded successfully. Remote file size: {remote_stat.st_size} bytes')
    sftp.close()

    # Step 2: Restart backend
    print('\n=== STEP 2: Restart backend ===')
    restart_cmd = 'pkill -f "uvicorn main:app" ; sleep 2 ; cd /root/voice-agent/backend && source venv/bin/activate && nohup uvicorn main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &'
    ssh_run(client, restart_cmd, timeout=30)

    # Step 3: Wait 3 seconds, then test
    print('\n=== STEP 3: Wait 3s, then test endpoint ===')
    time.sleep(3)

    test_cmd = 'curl -s -w "\nHTTP_CODE:%{http_code}\nTIME:%{time_total}s\n" -X POST http://localhost:8000/v1/chat/completions -H "Content-Type: application/json" -d ' + "'" + '{"model":"llama3.1:8b","messages":[{"role":"system","content":"You are a financial advisor"},{"role":"user","content":"hello"}],"temperature":0.0,"max_tokens":-1}' + "'"
    ssh_run(client, test_cmd, timeout=180)

    # Also check backend log
    print('\n=== Backend log (last 20 lines) ===')
    ssh_run(client, 'tail -20 /tmp/backend.log')

    client.close()
    print('\nDone.')

if __name__ == '__main__':
    main()
