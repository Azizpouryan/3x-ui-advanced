#!/bin/sh
set -e
case $1 in
    amd64)
        ARCH="64"
        FNAME="amd64"
        MTG_ARCH="amd64"
        ;;
    i386)
        ARCH="32"
        FNAME="i386"
        MTG_ARCH="386"
        ;;
    armv8 | arm64 | aarch64)
        ARCH="arm64-v8a"
        FNAME="arm64"
        MTG_ARCH="arm64"
        ;;
    armv7 | arm | arm32)
        ARCH="arm32-v7a"
        FNAME="arm32"
        MTG_ARCH="armv7"
        ;;
    armv6)
        ARCH="arm32-v6"
        FNAME="armv6"
        MTG_ARCH="armv6"
        ;;
    *)
        ARCH="64"
        FNAME="amd64"
        MTG_ARCH="amd64"
        ;;
esac
MTG_VER="2.2.8"
mkdir -p build/bin
cd build/bin
curl -sfLRO "https://github.com/XTLS/Xray-core/releases/download/v26.9.9/Xray-linux-${ARCH}.zip"
unzip "Xray-linux-${ARCH}.zip"
rm -f "Xray-linux-${ARCH}.zip" geoip.dat geosite.dat
mv xray "xray-linux-${FNAME}"
curl -sfLRO "https://github.com/9seconds/mtg/releases/download/v${MTG_VER}/mtg-${MTG_VER}-linux-${MTG_ARCH}.tar.gz"
tar -xzf "mtg-${MTG_VER}-linux-${MTG_ARCH}.tar.gz"
mv "mtg-${MTG_VER}-linux-${MTG_ARCH}/mtg" "mtg-linux-${FNAME}" 2>/dev/null || mv mtg "mtg-linux-${FNAME}"
rm -rf "mtg-${MTG_VER}-linux-${MTG_ARCH}" "mtg-${MTG_VER}-linux-${MTG_ARCH}.tar.gz"
chmod +x "mtg-linux-${FNAME}"
case $FNAME in
    amd64)
        curl -sfLRo "tuic-server" "https://github.com/EAimTY/tuic/releases/download/tuic-server-1.0.0/tuic-server-1.0.0-x86_64-unknown-linux-musl"
        ;;
    arm64)
        curl -sfLRo "tuic-server" "https://github.com/EAimTY/tuic/releases/download/tuic-server-1.0.0/tuic-server-1.0.0-aarch64-unknown-linux-musl"
        ;;
    arm32)
        curl -sfLRo "tuic-server" "https://github.com/EAimTY/tuic/releases/download/tuic-server-1.0.0/tuic-server-1.0.0-armv7-unknown-linux-musleabihf"
        ;;
    i386)
        curl -sfLRo "tuic-server" "https://github.com/EAimTY/tuic/releases/download/tuic-server-1.0.0/tuic-server-1.0.0-i686-unknown-linux-musl"
        ;;
esac
if [ -f "tuic-server" ]; then
    if [ ! -s "tuic-server" ]; then
        echo "DockerInit: tuic-server download was empty" >&2
        exit 1
    fi
    chmod +x "tuic-server"
fi
curl -sfLRO https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat
curl -sfLRO https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat
curl -sfLRo geoip_IR.dat https://github.com/chocolate4u/Iran-v2ray-rules/releases/latest/download/geoip.dat
curl -sfLRo geosite_IR.dat https://github.com/chocolate4u/Iran-v2ray-rules/releases/latest/download/geosite.dat
curl -sfLRo geoip_RU.dat https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geoip.dat
curl -sfLRo geosite_RU.dat https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geosite.dat
cd ../../
