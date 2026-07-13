#!/usr/bin/env python
"""
Quick-start script để setup environment cho testing.
Chạy: python tools/search/quickstart.py
"""

import os
import sys
import subprocess
from pathlib import Path


def print_header(text):
    """Print formatted header."""
    print(f"\n{'='*80}")
    print(f"  {text}")
    print(f"{'='*80}\n")


def check_groq_api_key():
    """Check if GROQ_API_KEY is set."""
    api_key = os.getenv("GROQ_API_KEY")
    
    print_header("🔐 GROQ_API_KEY Status")
    
    if api_key:
        print(f"✅ GROQ_API_KEY is SET")
        print(f"   Value: {api_key[:10]}...{api_key[-5:]}")
        return True
    else:
        print(f"❌ GROQ_API_KEY is NOT set")
        print(f"\n📋 To set GROQ_API_KEY:\n")
        print(f"  1. Get API key: https://console.groq.com/keys")
        print(f"\n  2. Set in PowerShell (temporary):")
        print(f"     $env:GROQ_API_KEY='gsk_your_key_here'")
        print(f"\n  3. Or create .env file:")
        print(f"     Copy .env.example to .env")
        print(f"     Edit .env and add: GROQ_API_KEY=gsk_...")
        print(f"\n  4. Or set permanent environment variable:")
        print(f"     [Environment]::SetEnvironmentVariable('GROQ_API_KEY', 'gsk_...', 'User')")
        return False


def check_port_forward():
    """Check if port-forward is available."""
    import socket
    
    print_header("📡 Port-Forward Status")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', 3550))
    sock.close()
    
    if result == 0:
        print(f"✅ Port 3550 is OPEN (product-catalog accessible)")
        return True
    else:
        print(f"❌ Port 3550 is CLOSED")
        print(f"\n📋 To open port-forward:\n")
        print(f"  kubectl port-forward svc/product-catalog 3550:3550")
        print(f"\n  Keep this terminal open while testing.")
        return False


def check_dependencies():
    """Check if required packages are installed."""
    print_header("📦 Dependencies Status")
    
    required = {
        "grpcio": "gRPC client",
        "groq": "Groq LLM API",
        "rapidfuzz": "Fuzzy string matching",
        "python-dotenv": "Environment variables",
    }
    
    missing = []
    
    for package, description in required.items():
        try:
            __import__(package)
            print(f"  ✅ {package:20} - {description}")
        except ImportError:
            print(f"  ❌ {package:20} - {description}")
            missing.append(package)
    
    if missing:
        print(f"\n⚠️  Missing packages: {', '.join(missing)}")
        print(f"\n  Install with:")
        print(f"    pip install {' '.join(missing)}")
        return False
    return True


def check_env_file():
    """Check if .env file exists."""
    print_header("📁 Environment File Status")
    
    env_file = Path(".env")
    env_example = Path(".env.example")
    
    if env_file.exists():
        print(f"✅ .env file EXISTS")
        # Check if GROQ_API_KEY is in .env
        with open(env_file) as f:
            content = f.read()
            if "GROQ_API_KEY" in content and "gsk_" in content:
                print(f"   ✅ GROQ_API_KEY found in .env")
                return True
            else:
                print(f"   ⚠️  GROQ_API_KEY not configured in .env")
    else:
        print(f"❌ .env file NOT found")
        
        if env_example.exists():
            print(f"\n📋 To create .env file:")
            print(f"  1. Copy .env.example to .env:")
            print(f"     cp .env.example .env")
            print(f"  2. Edit .env and add your GROQ_API_KEY")
        return False


def suggest_next_steps(groq_ok, port_ok, deps_ok):
    """Suggest next steps based on checks."""
    print_header("🚀 Next Steps")
    
    if not groq_ok:
        print("❌ Set GROQ_API_KEY first (see above)")
        return
    
    if not port_ok:
        print("⚠️  Port-forward not available")
        print("   → Tests will use mock mode or fail at gRPC phase")
        print("   → Set up port-forward for real search results:")
        print("     kubectl port-forward svc/product-catalog 3550:3550")
    
    if not deps_ok:
        print("❌ Install missing dependencies (see above)")
        return
    
    print("✅ All checks passed! Ready to test.\n")
    print("Choose test mode:\n")
    print("  1️⃣  Single query test:")
    print("     python tools/search/test_e2e.py \"kính thiên văn dưới 100 đô\"\n")
    print("  2️⃣  Batch test (6 predefined queries):")
    print("     python tools/search/test_e2e.py --batch\n")
    print("  3️⃣  Multiple custom queries:")
    print("     python tools/search/test_e2e.py \"query1\" \"query2\" \"query3\"\n")
    print("📖 For detailed guide, see: TESTING_GUIDE.md")


def main():
    """Run all checks."""
    print("\n" + "="*80)
    print("  🎯 Quick-Start Setup Check")
    print("="*80)
    
    groq_ok = check_groq_api_key()
    env_ok = check_env_file()
    port_ok = check_port_forward()
    deps_ok = check_dependencies()
    
    suggest_next_steps(groq_ok, port_ok, deps_ok)
    
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    main()
