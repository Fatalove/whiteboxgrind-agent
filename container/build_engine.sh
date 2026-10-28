#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C.UTF-8
work=/opt/wbg-engine
mkdir -p "$work/src/whiteboxgrind" "$work/src/tiny-AES-c" "$work/build/valgrind" "$work/prefix"
cd /vendor
sha256sum -c archives.sha256
tar -xzf whiteboxgrind-b4f5b78a415aaf4a864f31b9d85c3305a4970b4f.tar.gz -C "$work/src/whiteboxgrind" --strip-components=1
mkdir -p "$work/src/whiteboxgrind/cpp/asynchronous"
tar -xzf asynchronous-2584d9c314451d7afb318d36bd8c86bf57aa945a.tar.gz -C "$work/src/whiteboxgrind/cpp/asynchronous" --strip-components=1
tar -xzf tiny-AES-c-23856752fbd139da0b8ca6e471a13d5bcc99a08d.tar.gz -C "$work/src/tiny-AES-c" --strip-components=1
src="$work/src/whiteboxgrind"
prefix="$work/prefix"
(cd "$src" && patch --batch -p1 < /build/patch.patch)
export PATH="$prefix/bin:$PATH" PKG_CONFIG_PATH="$prefix/share/pkgconfig:$prefix/lib/pkgconfig" LD_LIBRARY_PATH="$prefix/lib"
(cd "$src/valgrind" && ./autogen.sh)
(cd "$work/build/valgrind" && "$src/valgrind/configure" --prefix="$prefix" && make -j1 && make -j1 install)
cmake -S "$src/y5" -B "$work/build/y5" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_INSTALL_LIBDIR=lib
cmake --build "$work/build/y5" --parallel 1
cmake --install "$work/build/y5"
cmake -S "$src/cpp" -B "$work/build/cpp" -DCMAKE_BUILD_TYPE=Release -DASYNCHRONOUS_INCLUDE_DIR="$src/cpp/asynchronous"
cmake --build "$work/build/cpp" --parallel 1
for tool in tracer filter unique leakage cpa info; do install -m755 "$work/build/cpp/$tool" "$prefix/bin/$tool"; done
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip install --only-binary=:all: --require-hashes -r /build/requirements.lock
pybind_include=$("$work/venv/bin/python" -c 'import pybind11; print(pybind11.get_include())')
numpy_include=$("$work/venv/bin/python" -c 'import numpy; print(numpy.get_include())')
(cd "$src/y5-python"; export CPLUS_INCLUDE_PATH="$prefix/include:$pybind_include:$numpy_include" LIBRARY_PATH="$prefix/lib"; \
 "$work/venv/bin/python" setup.py build_ext && "$work/venv/bin/python" setup.py install)
cp "$src/cpp/cpa.h" /tmp/wbg-cpa.h
rm -rf "$work/build" "$work/src/whiteboxgrind"
mkdir -p "$work/src/whiteboxgrind/cpp"
cp /tmp/wbg-cpa.h "$work/src/whiteboxgrind/cpp/cpa.h"
"$work/venv/bin/python" -m pip freeze > "$work/python-packages.txt"
find "$work" -type d -name __pycache__ -prune -exec rm -rf {} +
