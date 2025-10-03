# GeoCLIP GPU Server

Standalone FastAPI server for GPU-accelerated GeoCLIP predictions.

## Features

- GPU-accelerated predictions (CUDA 12.1)
- 24/7 auto-restart via Supervisor
- HTTP Basic Auth
- GET `/predict` (image URL) and POST `/predict` (file upload)  
- `/health` endpoint with GPU stats
- Multi-format image support (JPEG, PNG, HEIC, and other PIL-compatible formats)

## Setup on Vast.ai

### Step 1: Add Port 8000 to Instance

1. Go to https://cloud.vast.ai/instances/
2. Find your instance and click **"..."** → **"Edit"**
3. In **"Docker Options"**, add `-p 8000:8000` to the existing options:
   ```bash
   -p 1111:1111 -p 6006:6006 -p 8080:8080 -p 8384:8384 -p 8000:8000 ...
   ```
4. **Save** and **restart** the instance
5. Wait for instance to come back online

### Step 2: Find Your Public Port

1. Click **"IP Port Info"** button on your instance
2. Find the line showing port 8000:
   ```
   192.165.134.28:45678 -> 8000/tcp
   ```
3. Note the **public IP:port** (e.g., `192.165.134.28:45678`)

### Step 3: Deploy GPU Server

```bash
cd gpu_server
./deploy.sh root@<vast-ip> <ssh-port> ~/.ssh/id_vast admin mypassword
```

**Example:**
```bash
cd gpu_server
./deploy.sh root@192.165.134.28 11233 ~/.ssh/id_vast admin mypassword
```

**Note:** Replace `11233` with your actual SSH port (shown in instance dashboard)

### Step 4: Configure Main API

Update your main API `.env` file with the **public IP:port** from Step 2:

```bash
# .env
GPU_SERVER_URL=http://192.165.134.28:45678
GPU_SERVER_USERNAME=admin
GPU_SERVER_PASSWORD=securepass123
```

### Step 5: Test GPU Server

```bash
# Use the public IP:port from Step 2
curl -u admin:securepass123 http://192.165.134.28:45678/health
```

Expected response:
```json
{
  "status": "ok",
  "gpu": {
    "cuda_available": true,
    "gpu_name": "NVIDIA GeForce RTX 4070 Ti",
    "gpu_memory_allocated_gb": 1.63
  }
}
```

✅ **Done!** Your GPU server is now publicly accessible.

---

## Alternative: SSH Tunnel (No Port Configuration)

If you don't want to modify instance ports:

```bash
# Start tunnel (keep running)
ssh -i ~/.ssh/id_vast -p 11233 -N -L 8000:localhost:8000 root@192.165.134.28 &

# Configure API for localhost
GPU_SERVER_URL=http://localhost:8000
GPU_SERVER_USERNAME=admin
GPU_SERVER_PASSWORD=mypassword

# Test
curl -u admin:mypassword http://localhost:8000/health
```

---

## API Usage

### Health Check
```bash
curl -u admin:mypassword http://<gpu-server-url>/health
```

### Predict from URL
```bash
curl -u admin:mypassword \
  'http://<gpu-server-url>/predict?image_url=https://images.unsplash.com/photo-1506905925346-21bda4d32df4&top_k=5'
```

### Predict from Upload
```bash
# Supports JPEG, PNG, HEIC, and other PIL-compatible formats
curl -u admin:mypassword \
  -F file=@image.jpg \
  'http://<gpu-server-url>/predict?top_k=5'

# Example with HEIC file
curl -u admin:mypassword \
  -F file=@photo.heic \
  'http://<gpu-server-url>/predict?top_k=5'
```

## Management

### View Logs
```bash
ssh -i ~/.ssh/id_vast -p 11233 root@192.165.134.28 'tail -f ~/geoclip.log'
```

### Check Status
```bash
ssh -i ~/.ssh/id_vast -p 11233 root@192.165.134.28 'supervisorctl status geoclip'
```

### Restart Server
```bash
ssh -i ~/.ssh/id_vast -p 11233 root@192.165.134.28 'supervisorctl restart geoclip'
```

### Update Code
```bash
cd gpu_server
./deploy.sh root@192.165.134.28 11233 ~/.ssh/id_vast
```

## Environment Variables

- `APP_USERNAME` - Auth username (default: admin)
- `APP_PASSWORD` - Auth password (default: admin)
- `HOST` - Server host (default: 0.0.0.0)
- `PORT` - Server port (default: 8000)
