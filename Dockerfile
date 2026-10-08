ARG CUDA_IMAGE="nvidia/cuda:12.9.2-cudnn-devel-ubuntu24.04"
FROM ${CUDA_IMAGE}

# Install native build tools, python, and libraries
RUN apt-get update -qq && \
    apt-get install -y -qq git build-essential python3 python3-pip libcurl4-openssl-dev curl libgomp1 libicu-dev cmake nlohmann-json3-dev gh ccache && \
    rm -rf /var/lib/apt/lists/*

# Fix CUDA library stubs for the linker
RUN ln -s /usr/local/cuda/lib64/stubs/libcuda.so /usr/local/cuda/lib64/stubs/libcuda.so.1
ENV LIBRARY_PATH=/usr/local/cuda/lib64/stubs:$LIBRARY_PATH
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64/stubs:$LD_LIBRARY_PATH

# Setup app directory
WORKDIR /app

# Ensure Python output isn't buffered so logs stream cleanly
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python3", "/app/builder.py"]
