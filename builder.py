import os, time, json, subprocess, shutil, argparse, sys, zipfile
from datetime import datetime

CONFIG_FILE = "/app/config.json"
OUTPUT_BASE = "/output"
ARCHIVE_BASE = "/output/archives"
WORKSPACE = "/workspace"
STATE_FILE = os.path.join(OUTPUT_BASE, "state.json")
POLL_INTERVAL_SEC = 1800  # 30 minutes

state = {} # Stores { "repo_url": "last_commit_hash" }

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Failed to load state file: {e}")
    return {}

def save_state(state_data):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state_data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Failed to save state file: {e}")

def get_remote_commit(url):
    try:
        res = subprocess.run(["git", "ls-remote", url, "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.split()[0] if res.stdout else None
    except Exception as e:
        print(f"Error checking repo {url}: {e}")
        return None

def make_zip64(source_dir, dest_zip_path, file_filter=None):
    with zipfile.ZipFile(dest_zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
        for root, _, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if file.endswith(".zip"):
                    continue
                if file_filter and file not in file_filter:
                    continue
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)
    return dest_zip_path

def upload_to_github(repo_url, commit_hash, archive_dir, archive_bin_dir, output_folder, timestamp, upload_targets=None):
    print(f"📦 Zipping test data and preparing binary assets for GitHub...")
    clean_url = repo_url.rstrip("/").removesuffix(".git")
    owner_repo = "/".join(clean_url.split("/")[-2:])
    
    temp_test_zip = os.path.join("/tmp", f"temp_testlogs_{timestamp}.zip")
    make_zip64(archive_dir, temp_test_zip)
    final_test_zip = os.path.join(archive_dir, "Test Logs.zip")
    shutil.move(temp_test_zip, final_test_zip)
    
    tag_name = f"build-{output_folder.replace('/', '-')}-{timestamp}"
    upload_cmd = [
        "gh", "release", "create", tag_name, final_test_zip,
        "--repo", owner_repo,
        "--title", f"Automated Build: {tag_name}",
        "--notes", f"Automated build for commit {commit_hash}"
    ]
    
    if archive_bin_dir and os.path.exists(archive_bin_dir):
        bin_files = [
            f for f in os.listdir(archive_bin_dir) 
            if os.path.isfile(os.path.join(archive_bin_dir, f)) and not f.endswith(".zip")
        ]
        
        if upload_targets:
            bin_files = [f for f in bin_files if f in upload_targets]
            print(f"🎯 Filtered binary upload targets: {bin_files}")
        
        if len(bin_files) > 1:
            print(f"📦 Multiple binary files detected ({len(bin_files)}). Creating Binaries.zip...")
            temp_bin_zip = os.path.join("/tmp", f"temp_binaries_{timestamp}.zip")
            make_zip64(archive_bin_dir, temp_bin_zip, file_filter=bin_files)
            final_bin_zip = os.path.join(archive_dir, "Binaries.zip")
            shutil.move(temp_bin_zip, final_bin_zip)
            upload_cmd.append(final_bin_zip)
        elif len(bin_files) == 1:
            print(f"📦 Single binary file detected ({bin_files[0]}). Skipping zip packaging.")
            upload_cmd.append(os.path.join(archive_bin_dir, bin_files[0]))
        else:
            print(f"⚠️ No matching binaries found to upload.")
    
    try:
        subprocess.run(upload_cmd, check=True, capture_output=True, text=True)
        print(f"✅ Successfully uploaded release to GitHub: {owner_repo}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to upload to GitHub. Error: {e.stderr}")

def build_repo(repo, do_build=True, do_test=True, do_upload=True):
    url = repo["repo_url"]
    owner_name = "/".join(url.rstrip("/").split("/")[-2:])
    output_folder = repo.get("output_folder", owner_name)
    build_dir = repo.get("build", "build")
    target = repo.get("target", "all")
    faquants = repo.get("faquants", "")
    cuda_archs = repo.get("cuda_archs", "61;70") 
    upload_targets = repo.get("upload_target", []) 
    
    cmake_flags_list = [
        f'-DCMAKE_CUDA_ARCHITECTURES="{cuda_archs}"',
        "-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON",
        "-DCMAKE_INSTALL_RPATH='$ORIGIN'",
    ]
    
    if faquants:
        cmake_flags_list.append(f'-DGGML_CUDA_FA_QUANTS="{faquants}"')
        
    if repo.get("extra_flags"):
        cmake_flags_list.append(repo["extra_flags"])
        
    cmake_flags = " ".join(cmake_flags_list)
    ld_flags = repo.get("extra_ldflags", "")
    env = os.environ.copy()
    if ld_flags:
        env["LDFLAGS"] = ld_flags

    configure_cmd = f"cmake -S . -B {build_dir} {cmake_flags}"
    compile_cmd = f"cmake --build {build_dir} --target {target} --parallel 10"

    repo_path = os.path.join(WORKSPACE, owner_name)
    commit_hash = None
    archive_dir = None
    archive_bin_dir = None
    timestamp = None

    if do_build:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 Building {owner_name}...")
        
        if os.path.exists(repo_path): 
            shutil.rmtree(repo_path)
        subprocess.run(["git", "clone", "--recursive", url, repo_path], check=True)
        
        commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True).stdout.strip()
        commit_msg = subprocess.run(["git", "log", "-1", "--format=%s (%ci)"], cwd=repo_path, capture_output=True, text=True).stdout.strip()
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        live_dir = os.path.join(OUTPUT_BASE, output_folder)
        archive_dir = os.path.join(ARCHIVE_BASE, f"{output_folder.replace('/', '-')}-{timestamp}")
        archive_bin_dir = f"{archive_dir}-binaries"
        
        os.makedirs(live_dir, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)
        os.makedirs(archive_bin_dir, exist_ok=True)
        
        build_log_path = os.path.join(archive_dir, "build.log")

        try:
            with open(build_log_path, "w") as log_file:
                print("🛠️ Configuring...")
                subprocess.run(configure_cmd, shell=True, cwd=repo_path, env=env, check=True, stdout=log_file, stderr=subprocess.STDOUT)
                
                print("🔨 Compiling...")
                subprocess.run(compile_cmd, shell=True, cwd=repo_path, env=env, check=True, stdout=log_file, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            print(f"❌ Build failed for {owner_name}. Check {build_log_path}")
            return commit_hash

        bin_path = os.path.join(repo_path, build_dir, "bin")
        if not os.path.exists(bin_path):
            print(f"❌ Build failed or bin directory missing for {owner_name}")
            return commit_hash

        with open(os.path.join(bin_path, "build_info.txt"), "w") as f:
            f.write(f"Commit: {commit_hash}\nMessage: {commit_msg}\nBuilt: {timestamp}\n")
            f.write(f"Configure Cmd: {configure_cmd}\n")
            f.write(f"Compile Cmd: {compile_cmd}\n")

        for file in os.listdir(bin_path):
            shutil.copy2(os.path.join(bin_path, file), live_dir)
            shutil.copy2(os.path.join(bin_path, file), archive_bin_dir)

        subprocess.run(f"cp /usr/lib/x86_64-linux-gnu/libicu*.so.70* {live_dir}/ 2>/dev/null || true", shell=True)
        subprocess.run(f"cp /usr/lib/x86_64-linux-gnu/libicu*.so.70* {archive_bin_dir}/ 2>/dev/null || true", shell=True)
        
        print(f"✅ Successfully deployed binaries to {live_dir}")

    else:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔎 Bypassing build for {owner_name}. Fetching existing artifacts...")
        if not os.path.exists(repo_path):
            print(f"❌ Workspace missing for {owner_name}. Cannot test or upload without an existing workspace.")
            return None
            
        commit_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True).stdout.strip()
        
        archive_prefix = output_folder.replace('/', '-')
        if not os.path.exists(ARCHIVE_BASE):
            print(f"❌ Archive base directory missing.")
            return commit_hash
            
        archives = [d for d in os.listdir(ARCHIVE_BASE) if d.startswith(archive_prefix + "-") and not d.endswith("-binaries") and os.path.isdir(os.path.join(ARCHIVE_BASE, d))]
        if not archives:
            print(f"❌ No existing archives found for {owner_name}.")
            return commit_hash
            
        latest_archive = sorted(archives)[-1]
        archive_dir = os.path.join(ARCHIVE_BASE, latest_archive)
        archive_bin_dir = f"{archive_dir}-binaries"
        timestamp = latest_archive.replace(archive_prefix + "-", "")

    # 5. Run Tests
    if do_test:
        test_cmds = repo.get("test_commands") or repo.get("test_command", [])
        if isinstance(test_cmds, str):
            test_cmds = [test_cmds]

        if test_cmds:
            test_gpus = repo.get("test_gpus", ["0"])
            # Pull the arena_mib mapping from JSON, empty by default
            gpu_arena_mib = repo.get("gpu_arena_mib", {})
            
            print(f"🧪 Running {len(test_cmds)} test suite(s) on GPUs {', '.join(map(str, test_gpus))}...")
            
            for gpu_id in test_gpus:
                gpu_id_str = str(gpu_id)
                # Fetch size, default to 5000 if not defined
                arena_size = gpu_arena_mib.get(gpu_id_str, "5000")
                
                print(f"   ▶️ Starting tests on GPU {gpu_id_str} (Arena MIB: {arena_size})...")
                
                for cmd_idx, test_cmd_template in enumerate(test_cmds, start=1):
                    log_prefix = f"test{cmd_idx}" if len(test_cmds) > 1 else "test"
                    test_log_path = os.path.join(archive_dir, f"{log_prefix}_gpu{gpu_id_str}.log")
                    
                    # Inject all variables, including arena_mib
                    test_cmd = test_cmd_template.format(
                        archive_dir=archive_dir, 
                        gpu_id=gpu_id_str, 
                        arena_mib=arena_size
                    )
                    
                    test_env = env.copy()
                    if "LD_LIBRARY_PATH" in test_env:
                        test_env["LD_LIBRARY_PATH"] = ":".join(
                            [p for p in test_env["LD_LIBRARY_PATH"].split(":") if "stubs" not in p]
                        )
                    test_env["CUDA_VISIBLE_DEVICES"] = gpu_id_str

                    with open(test_log_path, "w") as tlog:
                        try:
                            subprocess.run(test_cmd, shell=True, cwd=repo_path, env=test_env, check=True, stdout=tlog, stderr=subprocess.STDOUT)
                            print(f"      ✅ Test {cmd_idx}/{len(test_cmds)} passed on GPU {gpu_id_str}.")
                        except subprocess.CalledProcessError:
                            print(f"      ⚠️ Test {cmd_idx}/{len(test_cmds)} failed on GPU {gpu_id_str}. Check {test_log_path}")
        else:
            print(f"ℹ️ No test commands specified in config for {owner_name}. Skipping tests.")

    if do_upload:
        upload_url = repo.get("test_upload_url")
        if upload_url:
            upload_to_github(upload_url, commit_hash, archive_dir, archive_bin_dir, output_folder, timestamp, upload_targets=upload_targets)
        else:
            print(f"ℹ️ No test_upload_url specified in config for {owner_name}. Skipping upload.")

    return commit_hash

def main():
    global state
    parser = argparse.ArgumentParser(description="Build Daemon for GitHub Repos")
    parser.add_argument("--build", type=int, help="Force build + test repo at 1-based index (skip upload)")
    parser.add_argument("--test", type=int, help="Force test repo at 1-based index (skip build and upload)")
    parser.add_argument("--upload", type=int, help="Force upload repo at 1-based index (skip build and test)")
    parser.add_argument("--buildupload", type=int, help="Force build, test, and upload repo at 1-based index")
    args = parser.parse_args()

    if not os.path.exists(CONFIG_FILE):
        print(f"❌ Config file missing at {CONFIG_FILE}")
        sys.exit(1)
        
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    repos = config.get("repos", [])

    if args.build or args.test or args.upload or args.buildupload:
        target_idx = args.build or args.test or args.upload or args.buildupload
        if not (1 <= target_idx <= len(repos)):
            print(f"❌ Invalid repo index {target_idx}. JSON contains {len(repos)} repos (Valid range: 1 to {len(repos)}).")
            sys.exit(1)
            
        repo = repos[target_idx - 1]
        do_build = bool(args.build or args.buildupload)
        do_test = bool(args.build or args.test or args.buildupload)
        do_upload = bool(args.upload or args.buildupload)
        
        print(f"🤖 Manual mode triggered for repo index {target_idx}: {repo['repo_url']}")
        try:
            result_hash = build_repo(repo, do_build=do_build, do_test=do_test, do_upload=do_upload)
            if result_hash and do_build:
                state = load_state()
                state[repo["repo_url"]] = result_hash
                save_state(state)
        except Exception as e:
            print(f"❌ Failed to process manually: {e}")
            
        print("✅ Manual execution completed.")
        sys.exit(0)

    state = load_state()
    print("🤖 Build Daemon Started. Polling every 30 minutes.")
    while True:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
            
        for repo in config.get("repos", []):
            url = repo["repo_url"]
            latest_hash = get_remote_commit(url)
            
            if not latest_hash:
                continue
                
            if state.get(url) != latest_hash:
                print(f"\n🔔 New commit detected for {url}: {latest_hash}")
                try:
                    result_hash = build_repo(repo, do_build=True, do_test=True, do_upload=True)
                    if result_hash:
                        state[url] = result_hash
                        save_state(state)
                except Exception as e:
                    print(f"❌ Failed to process {url}: {e}")
            else:
                pass # Silent poll
                
        time.sleep(POLL_INTERVAL_SEC)

if __name__ == "__main__":
    main()
