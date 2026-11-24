"""Zip the files CodeBuild needs to build an AgentCore image, and nothing else.

    py -3.12 deploy/agentcore/package_source.py mcp <out.zip>

Only allow-listed paths go in (no .env, keys, notebooks or data), so secrets can't leak into a
build. Upload the zip to the build bucket and start the CodeBuild project (see README).
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGES = {
    "mcp": ["agents/*.py", "mcp_server.py",
            "deploy/agentcore/mcp/Dockerfile", "deploy/agentcore/mcp/requirements.txt",
            "deploy/agentcore/mcp/buildspec.yml"],
}


def package(image, out):
    files = sorted({p for pattern in IMAGES[image] for p in ROOT.glob(pattern) if p.is_file()})
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
    return [p.relative_to(ROOT).as_posix() for p in files]


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in IMAGES:
        sys.exit(__doc__)
    for name in package(sys.argv[1], sys.argv[2]):
        print(name)
