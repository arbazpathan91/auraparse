import os
import requests
import base64
import time
import concurrent.futures
import mimetypes
import json
import statistics
from datetime import datetime

# ================= CONFIGURATION =================
API_URL = "https://receipt-scanner-1063448783198.us-central1.run.app/api/v1/extract"
API_KEY = "rcp_live_Uv8PkwjXGKz-qxQq1j3U8jV-i21FL7sFBfMR6kiDZ3Y"  # <--- UPDATE THIS
INPUT_FOLDER = "./image"
OUTPUT_FILE = "benchmark_results.json"
MAX_THREADS = 20  # Safe number for stress testing
# =================================================

def process_file(file_info):
    """
    Process a single file. 
    Returns a dictionary of metrics.
    """
    index, total_files, filename = file_info
    filepath = os.path.join(INPUT_FOLDER, filename)
    
    # Skip non-images
    if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf')):
        return None

    mime_type, _ = mimetypes.guess_type(filepath)
    if not mime_type: mime_type = "image/png"
    
    result = {
        "filename": filename,
        "timestamp": datetime.now().isoformat(),
        "status": "error",
        "status_code": 0,
        "latency_seconds": 0,
        "data": None,
        "error_msg": None
    }

    try:
        # Read and Encode
        with open(filepath, "rb") as f:
            base64_image = base64.b64encode(f.read()).decode('utf-8')

        # ---------------------------------------------
        # TIMER START
        start_time = time.time()
        
        response = requests.post(
            API_URL,
            headers={
                "Content-Type": "application/json", 
                "X-API-Key": API_KEY
            },
            json={
                # CHANGED: 'image' -> 'file_data'
                "file_data": base64_image, 
                "mime_type": mime_type,
                # OPTIONAL: Explicitly tell API these are receipts
                "doc_type": "receipt" 
            },
            timeout=120 
        )
        
        # TIMER END
        duration = time.time() - start_time
        # ---------------------------------------------

        result["latency_seconds"] = round(duration, 4)
        result["status_code"] = response.status_code

        if response.status_code == 200:
            result["status"] = "success"
            result["data"] = response.json()
        else:
            result["status"] = "failed"
            result["error_msg"] = response.text

    except Exception as e:
        result["status"] = "exception"
        result["error_msg"] = str(e)

    # Simple progress indicator (thread safe enough for this usage)
    print(f"\rProgress: [{index}/{total_files}] Completed", end="", flush=True)
    
    return result

def main():
    if not os.path.exists(INPUT_FOLDER):
        print(f"Error: Folder '{INPUT_FOLDER}' not found.")
        return

    files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf'))]
    
    if not files:
        print("No files found.")
        return

    print(f"🚀 Starting Benchmark on {len(files)} files")
    print(f"⚡ Concurrency: {MAX_THREADS} threads")
    print("⏳ Please wait...\n")
    
    global_start = time.time()

    # Prepare arguments with indices for progress tracking
    file_args = [(i+1, len(files), f) for i, f in enumerate(files)]

    all_metrics = []
    
    # Run ThreadPool
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        # map returns results in order
        results = list(executor.map(process_file, file_args))
        
        # Filter out skipped files (None)
        all_metrics = [r for r in results if r is not None]

    total_duration = time.time() - global_start
    print("\n\n✅ Benchmark Complete!")

    # --- Calculate Statistics ---
    successful_reqs = [r for r in all_metrics if r["status"] == "success"]
    latencies = [r["latency_seconds"] for r in successful_reqs]
    
    stats = {
        "summary": {
            "total_requests": len(all_metrics),
            "successful": len(successful_reqs),
            "failed": len(all_metrics) - len(successful_reqs),
            "total_benchmark_time": round(total_duration, 2),
            "throughput_rps": round(len(all_metrics) / total_duration, 2)
        },
        "latency_metrics": {
            "avg": 0,
            "min": 0,
            "max": 0,
            "p50_median": 0,
            "p95": 0,
            "p99": 0
        }
    }

    if latencies:
        stats["latency_metrics"]["avg"] = round(statistics.mean(latencies), 4)
        stats["latency_metrics"]["min"] = round(min(latencies), 4)
        stats["latency_metrics"]["max"] = round(max(latencies), 4)
        stats["latency_metrics"]["p50_median"] = round(statistics.median(latencies), 4)
        # Calculate P95 and P99
        latencies.sort()
        stats["latency_metrics"]["p95"] = round(latencies[int(len(latencies) * 0.95)], 4)
        stats["latency_metrics"]["p99"] = round(latencies[int(len(latencies) * 0.99)], 4)

    # Save to File
    final_output = {
        "statistics": stats,
        "results": all_metrics
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(final_output, f, indent=2)

    # Print Summary to Console
    print("="*40)
    print(f"📊 Success Rate:   {len(successful_reqs)}/{len(all_metrics)}")
    print(f"⏱️  Average Latency: {stats['latency_metrics']['avg']}s")
    print(f"⏱️  Median (P50):    {stats['latency_metrics']['p50_median']}s")
    print(f"⏱️  95th % (P95):    {stats['latency_metrics']['p95']}s")
    print(f"💾 Full report saved to: {OUTPUT_FILE}")
    print("="*40)

if __name__ == "__main__":
    main()