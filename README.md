# Llama / C++ Automated Build & Benchmark Daemon

An automated, containerized build daemon designed to poll Git repositories, compile CUDA/C++ binaries (such as `llama.cpp` forks), run automated benchmarks across multiple GPUs with isolated environments, and publish release artifacts to GitHub Releases.

---

## Releases

The releases in this repository are outputs of this builder for different forks of llama.cpp, incuding the binary for P40 and V100 Nvidia Cards. Please refer to each repository for license information.

* https://github.com/RaymondHuang210129/llama.cpp-adaptive-kv-streaming
* https://github.com/troed/llama.cpp-adaptive-kv-streaming
* 

## Features

* **Continuous Polling & Persistence**: Automatically monitors remote repositories for new commits and persists state across container restarts (`state.json`).
* **Multi-GPU Testing Support**: Iterates through target CUDA devices (`CUDA_VISIBLE_DEVICES=0`, `1`, etc.), isolating environments and automatically bypassing CUDA driver stubs.
* **Flexible Dynamic Formatting**: Injects placeholders like `{archive_dir}`, `{gpu_id}`, and per-GPU parameter overrides like `{arena_mib}` directly into test commands.
* **Multiple Test Suites**: Supports running single strings or arrays of multiple test/benchmark commands per GPU.
* **Automated Artifact Bundling**:
* Deploys active binaries to a live directory.
* Creates ZIP64-compliant archives for benchmark logs and results.
* Auto-zips binaries when multiple output targets are built, or uploads uncompressed single binaries.


* **Selective GitHub Releases**: Uses the GitHub CLI (`gh`) to push release packages to specified target repositories, with support for filtering uploaded binary targets (`upload_target`).
* **Manual One-Shot Overrides**: Command-line flags to manually trigger build, test, upload, or build+upload sequences for any repository in your configuration.

---

## Prerequisites

* **NVIDIA GPU Driver & Container Toolkit**: Installed on the host system to expose GPUs to the Docker container (`--gpus all`).
* **GitHub Personal Access Token**: A token with `repo` scope passed via the `GITHUB_TOKEN` environment variable for `gh` CLI uploads.

---

## Configuration (`config.json`)

Place your repository configurations in `/app/config.json`. The daemon reloads this file automatically when mounted as a directory volume.

### Example `config.json`

```json
{
  "repos": [
    {
      "repo_url": "https://github.com/RaymondHuang210129/llama.cpp-adaptive-kv-streaming",
      "output_folder": "llama-cpp-v2",
      "build": "build-v2",
      "target": "all",
      "cuda_archs": "61;70;80;89;90",
      "extra_flags": "-DGGML_CUDA=ON -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release -DICU_USE_STATIC_LIBS=ON -DGGML_CUDA_FA=ON -DGGML_CUDA_FA_ALL_QUANTS=ON  -DLLAMA_BUILD_TESTS=ON",
      "upload_target": ["llama-server"],
      "test_upload_url": "https://github.com/rafaelmuylaert/llama-builder-tests",
      "test_gpus": ["0", "1"],
      "gpu_arena_mib": {
          "0": "2000",
          "1": "10000"
      },
      "test_commands": [
        "python3 benchmarks/run-fixed-span-sweep.py --model /models/Qwen3.8-27B-UD-IQ4_XS.gguf --server ./build-v2/bin/llama-server --mtp-lengths 0,1,2,3 --arena-mib {arena_mib} --output {archive_dir}/CUDA{gpu_id}_sweep1 --no-manage-production --context-step 65536 --batch-size 256 --ubatch-size 256",
        "./build-v2/bin/test-cuda-compiled-features",
        "./build-v2/bin/test-kv-stream-model --cuda-native-admission",
        "./build-v2/bin/test-kv-stream-context --model /models/Qwen3.8-27B-UD-IQ4_XS.gguf --embedded-mtp-pair",
        "./build-v2/bin/test-kv-stream-context --model /models/Qwen3.8-27B-UD-IQ4_XS.gguf --target-stream-tg4",
        "./build-v2/bin/test-kv-stream-context --model /models/Qwen3.8-27B-UD-IQ4_XS.gguf --resume-only"
        ]
    }
  ]
}

```

### Configuration Parameters

| Field | Type | Description |
| --- | --- | --- |
| `repo_url` | String | Target Git repository URL to clone and poll. |
| `output_folder` | String | Folder name inside `/output` for deployed live binaries. |
| `build` | String | Build output directory name (default: `"build"`). |
| `target` | String | CMake target to build (e.g., `"all"`, `"llama-server"`). |
| `cuda_archs` | String | Semicolon-separated CUDA compute architectures. |
| `extra_flags` | String | Additional CMake flags passed during configuration. |
| `upload_target` | Array | Optional list of specific binary filenames to upload to GitHub Releases. |
| `test_upload_url` | String | GitHub repository URL where release artifacts will be uploaded. |
| `test_gpus` | Array | List of GPU IDs to run tests against (e.g., `["0", "1"]`). |
| `gpu_arena_mib` | Object | Key-value mapping of GPU ID to custom `{arena_mib}` values. |
| `test_commands` | Array/String | Commands to execute sequentially per GPU. |

---

## Command Template Variables

You can use the following placeholders inside your `test_commands`:

* `{archive_dir}`: Path to the timestamped archive output directory for the current run.
* `{gpu_id}`: The current GPU ID being tested (e.g., `0`, `1`).
* `{arena_mib}`: The GPU-specific memory arena value pulled from `gpu_arena_mib`.

---

## Docker Setup

### 1. `docker-compose.yml`

> **Note:** Mount the entire project directory (`/srv/media/CodeProjects/llama-builder:/app`) rather than single files so editing `config.json` on the host reflects inside the container without requiring a container restart.

```yaml
version: "3.8"

services:
  llama-builder:
    build: .
    container_name: llama-builder
    restart: unless-stopped
    environment:
      - GITHUB_TOKEN=your_github_token_here
    volumes:
      - /path/to/config/folder:/app:ro
      - /path/to/output/folder:/output
      - /path/to/models/folder:/models:ro
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

```

### 2. Build and Run

```bash
docker compose up -d --build

```

---

## CLI Usage (Manual Overrides)

You can run manual one-shot operations for a specific repository by index (1-based index matching the order in `config.json`):

```bash
# Force build and test for the 1st repo in config.json (skip GitHub upload)
python3 builder.py --build 1

# Force run tests for the 1st repo (skip clean build and upload)
python3 builder.py --test 1

# Upload existing build/test artifacts for the 1st repo to GitHub
python3 builder.py --upload 1

# Force complete pipeline (build, test, upload) for the 1st repo
python3 builder.py --buildupload 1

```

---

## 📄 License

MIT License. Feel free to modify and use in your build workflows.
