import os
import subprocess
import sys

from dotenv import load_dotenv


def main() -> int:
    """加载 .env 文件并执行签到脚本，透传退出码。"""
    load_dotenv()
    print(".env 文件已加载，正在准备执行签到脚本...")
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodeseek_sign.py")
    return subprocess.run([sys.executable, script_path], cwd=os.path.dirname(script_path)).returncode


if __name__ == "__main__":
    sys.exit(main())
