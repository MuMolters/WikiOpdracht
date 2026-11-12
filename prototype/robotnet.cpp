#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <timeapi.h>
#pragma comment(lib, "Ws2_32.lib")
#pragma comment(lib, "Winmm.lib")
using sock_t = SOCKET;
static void close_sock(sock_t s) { closesocket(s); }
static bool sock_ok(sock_t s) { return s != INVALID_SOCKET; }
#else
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
using sock_t = int;
static const sock_t INVALID_SOCKET = -1;
static void close_sock(sock_t s) { close(s); }
static bool sock_ok(sock_t s) { return s >= 0; }
#endif

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

using namespace std::chrono;

static const uint32_t MAGIC = 0x524F424F;  
static const uint32_t MODE_UPLOAD = 1;    
static const uint32_t MODE_DOWNLOAD = 2; 

static int64_t now_ns() {
    return duration_cast<nanoseconds>(steady_clock::now().time_since_epoch()).count();
}

static std::string timestamp() {
    std::time_t t = std::time(nullptr);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm);
    return buf;
}

// ---------------------------------------------------------------- socket helpers

static bool send_all(sock_t s, const char* buf, size_t len) {
    while (len > 0) {
        int chunk = (int)std::min<size_t>(len, 1 << 20);
        int n = send(s, buf, chunk, 0);
        if (n <= 0) return false;
        buf += n;
        len -= (size_t)n;
    }
    return true;
}

static bool recv_all(sock_t s, char* buf, size_t len) {
    while (len > 0) {
        int chunk = (int)std::min<size_t>(len, 1 << 20);
        int n = recv(s, buf, chunk, 0);
        if (n <= 0) return false;
        buf += n;
        len -= (size_t)n;
    }
    return true;
}

static void set_nodelay(sock_t s) {
    int one = 1;
    setsockopt(s, IPPROTO_TCP, TCP_NODELAY, (const char*)&one, sizeof(one));
}

static void set_recv_timeout(sock_t s, int ms) {
#ifdef _WIN32
    DWORD t = (DWORD)ms;
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char*)&t, sizeof(t));
#else
    timeval tv{ms / 1000, (ms % 1000) * 1000};
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
#endif
}

static bool resolve(const std::string& host, uint16_t port, sockaddr_in& out) {
    addrinfo hints{};
    hints.ai_family = AF_INET;
    addrinfo* res = nullptr;
    if (getaddrinfo(host.c_str(), nullptr, &hints, &res) != 0 || !res) return false;
    out = *(sockaddr_in*)res->ai_addr;
    out.sin_port = htons(port);
    freeaddrinfo(res);
    return true;
}

static void fill_payload(std::vector<char>& buf) {
    // Niet-comprimeerbare inhoud (eenvoudige PRNG), zodat de link echte bytes vervoert.
    uint32_t x = 2463534242u;
    for (auto& c : buf) {
        x ^= x << 13; x ^= x >> 17; x ^= x << 5;
        c = (char)(x & 0xFF);
    }
}

// ---------------------------------------------------------------- server

static void udp_echo_loop(uint16_t port) {
    sock_t u = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    int big = 4 << 20;
    setsockopt(u, SOL_SOCKET, SO_RCVBUF, (const char*)&big, sizeof(big));
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = INADDR_ANY;
    a.sin_port = htons(port);
    if (bind(u, (sockaddr*)&a, sizeof(a)) != 0) {
        std::cerr << "[udp] bind mislukt op poort " << port << "\n";
        return;
    }
    std::vector<char> pkt(65536);
    for (;;) {
        sockaddr_in from{};
        socklen_t fl = sizeof(from);
        int n = recvfrom(u, pkt.data(), (int)pkt.size(), 0, (sockaddr*)&from, &fl);
        if (n <= 0) continue; 
        sendto(u, pkt.data(), n, 0, (sockaddr*)&from, fl);  // echo terug naar robot
    }
}

static void handle_tcp_client(sock_t c, const std::string& who) {
    set_nodelay(c);
    uint32_t hdr[3];
    if (!recv_all(c, (char*)hdr, sizeof(hdr))) return;
    uint32_t mode = ntohl(hdr[0]), size = ntohl(hdr[1]), count = ntohl(hdr[2]);
    if (size == 0 || size > (64u << 20) || count == 0 || count > 100000) {
        std::cerr << "[tcp] ongeldige header van " << who << "\n";
        return;
    }
    std::cout << "[tcp] " << who << " " << (mode == MODE_UPLOAD ? "upload" : "download")
              << " " << size << " B x " << count << "\n";
    std::vector<char> buf(size);
    fill_payload(buf);
    const char ack = 'A';
    for (uint32_t i = 0; i < count; ++i) {
        if (mode == MODE_UPLOAD) {
            if (!recv_all(c, buf.data(), size)) break;
            if (!send_all(c, &ack, 1)) break;
        } else if (mode == MODE_DOWNLOAD) {
            char req;
            if (!recv_all(c, &req, 1)) break;
            if (!send_all(c, buf.data(), size)) break;
        } else {
            break;
        }
    }
}

static int run_server(uint16_t port) {
    std::thread(udp_echo_loop, port).detach();

    sock_t l = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    int one = 1;
    setsockopt(l, SOL_SOCKET, SO_REUSEADDR, (const char*)&one, sizeof(one));
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = INADDR_ANY;
    a.sin_port = htons(port);
    if (bind(l, (sockaddr*)&a, sizeof(a)) != 0 || listen(l, 8) != 0) {
        std::cerr << "[tcp] bind/listen mislukt op poort " << port << "\n";
        return 1;
    }
    std::cout << "Fleet manager actief op TCP+UDP poort " << port << " (Ctrl+C om te stoppen)\n";
    for (;;) {
        sockaddr_in from{};
        socklen_t fl = sizeof(from);
        sock_t c = accept(l, (sockaddr*)&from, &fl);
        if (!sock_ok(c)) continue;
        char ip[INET_ADDRSTRLEN] = {0};
        inet_ntop(AF_INET, &from.sin_addr, ip, sizeof(ip));
        handle_tcp_client(c, ip);
        close_sock(c);
    }
}

// ---------------------------------------------------------------- client (robot)

struct Sample {
    std::string test, proto, direction;
    uint32_t size = 0, seq = 0;
    double ms = NAN, mbps = NAN;
    int lost = 0;
};

struct TestDef {
    std::string name;
    bool udp;
    uint32_t mode;   // TCP: upload/download
    uint32_t size;   // bytes per bericht
    double hz;       // UDP: verzendfrequentie
    uint32_t count;  // TCP: aantal berichten
};

static std::vector<Sample> udp_test(const sockaddr_in& addr, const TestDef& t, double seconds) {
    std::vector<Sample> out;
    sock_t u = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (connect(u, (const sockaddr*)&addr, sizeof(addr)) != 0) {
        std::cerr << "  UDP connect mislukt\n";
        close_sock(u);
        return out;
    }
    int big = 4 << 20;
    setsockopt(u, SOL_SOCKET, SO_RCVBUF, (const char*)&big, sizeof(big));
    set_recv_timeout(u, 200);

    const uint32_t n = (uint32_t)std::lround(t.hz * seconds);
    std::vector<int64_t> sent(n, 0);
    std::unique_ptr<std::atomic<int64_t>[]> recvd(new std::atomic<int64_t>[n]);
    for (uint32_t i = 0; i < n; ++i) recvd[i].store(0);
    std::atomic<bool> stop{false};

    // Ontvangthread: noteert per volgnummer het moment van terugkomst.
    std::thread rx([&] {
        std::vector<char> b(65536);
        while (!stop.load()) {
            int r = recv(u, b.data(), (int)b.size(), 0);
            if (r < 8) continue;
            uint32_t seq, mg;
            std::memcpy(&seq, b.data(), 4);
            std::memcpy(&mg, b.data() + 4, 4);
            if (ntohl(mg) != MAGIC) continue;
            seq = ntohl(seq);
            int64_t zero = 0;
            if (seq < n) recvd[seq].compare_exchange_strong(zero, now_ns());
        }
    });

    std::vector<char> pkt(std::max<uint32_t>(t.size, 8), 0);
    const uint32_t mg = htonl(MAGIC);
    const auto interval = nanoseconds((int64_t)(1e9 / t.hz));
    auto next = steady_clock::now();
    for (uint32_t i = 0; i < n; ++i) {
        uint32_t s = htonl(i);
        std::memcpy(pkt.data(), &s, 4);
        std::memcpy(pkt.data() + 4, &mg, 4);
        sent[i] = now_ns();
        send(u, pkt.data(), (int)pkt.size(), 0);
        next += interval;
        std::this_thread::sleep_until(next);
    }
    std::this_thread::sleep_for(std::chrono::seconds(2));  // late pakketten nog opvangen
    stop.store(true);
    rx.join();
    close_sock(u);

    for (uint32_t i = 0; i < n; ++i) {
        Sample s;
        s.test = t.name; s.proto = "UDP"; s.direction = "echo";
        s.size = t.size; s.seq = i;
        int64_t r = recvd[i].load();
        if (r == 0) {
            s.lost = 1;
        } else {
            s.ms = (r - sent[i]) / 1e6;
        }
        out.push_back(s);
    }
    return out;
}

static std::vector<Sample> tcp_test(const sockaddr_in& addr, const TestDef& t) {
    std::vector<Sample> out;
    sock_t s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (connect(s, (const sockaddr*)&addr, sizeof(addr)) != 0) {
        std::cerr << "  TCP connect mislukt (draait de server? firewall?)\n";
        close_sock(s);
        return out;
    }
    set_nodelay(s);
    uint32_t hdr[3] = {htonl(t.mode), htonl(t.size), htonl(t.count)};
    bool ok = send_all(s, (const char*)hdr, sizeof(hdr));

    std::vector<char> buf(t.size);
    fill_payload(buf);
    const char req = 'R';
    for (uint32_t i = 0; i < t.count; ++i) {
        Sample smp;
        smp.test = t.name; smp.proto = "TCP";
        smp.direction = (t.mode == MODE_UPLOAD) ? "up" : "down";
        smp.size = t.size; smp.seq = i;
        if (ok) {
            int64_t t0 = now_ns();
            if (t.mode == MODE_UPLOAD) {
                char ack;
                ok = send_all(s, buf.data(), t.size) && recv_all(s, &ack, 1);
            } else {
                ok = send_all(s, &req, 1) && recv_all(s, buf.data(), t.size);
            }
            int64_t t1 = now_ns();
            if (ok) {
                smp.ms = (t1 - t0) / 1e6;
                smp.mbps = (t.size * 8.0 / 1e6) / ((t1 - t0) / 1e9);
            }
        }
        if (!ok) smp.lost = 1;  // verbinding verbroken
        out.push_back(smp);
    }
    close_sock(s);
    return out;
}

static double percentile(std::vector<double> v, double p) {
    if (v.empty()) return NAN;
    std::sort(v.begin(), v.end());
    double idx = p * (v.size() - 1);
    size_t lo = (size_t)std::floor(idx), hi = (size_t)std::ceil(idx);
    return v[lo] + (v[hi] - v[lo]) * (idx - lo);
}

static void print_summary(const TestDef& t, const std::vector<Sample>& s) {
    std::vector<double> ms, mbps;
    int lost = 0;
    double jitter_sum = 0;
    int jitter_n = 0;
    double prev = NAN;
    for (auto& x : s) {
        if (x.lost) { ++lost; continue; }
        ms.push_back(x.ms);
        if (!std::isnan(x.mbps)) mbps.push_back(x.mbps);
        if (!std::isnan(prev)) { jitter_sum += std::fabs(x.ms - prev); ++jitter_n; }
        prev = x.ms;
    }
    double mean = 0;
    for (double v : ms) mean += v;
    mean = ms.empty() ? NAN : mean / ms.size();
    std::cout << std::fixed << std::setprecision(2) << "  " << std::left << std::setw(16) << t.name
              << " n=" << std::setw(5) << s.size()
              << " loss=" << std::setw(6) << (s.empty() ? 0.0 : 100.0 * lost / s.size()) << "%"
              << " gem=" << std::setw(9) << mean << "ms"
              << " p95=" << std::setw(9) << percentile(ms, 0.95) << "ms";
    if (t.udp) {
        std::cout << " jitter=" << (jitter_n ? jitter_sum / jitter_n : NAN) << "ms";
    } else {
        double m = 0;
        for (double v : mbps) m += v;
        std::cout << " doorvoer=" << (mbps.empty() ? NAN : m / mbps.size()) << " Mbps";
    }
    std::cout << "\n";
}

static void append_csv(const std::string& path, const std::string& when, const std::string& network,
                       const std::string& location, int run, const std::vector<Sample>& s) {
    bool fresh;
    {
        std::ifstream probe(path);
        fresh = !probe.good() || probe.peek() == std::ifstream::traits_type::eof();
    }
    std::ofstream f(path, std::ios::app);
    if (fresh)
        f << "timestamp,network,location,run,test,proto,direction,size_bytes,seq,ms,mbps,lost\n";
    f << std::fixed << std::setprecision(4);
    for (auto& x : s) {
        f << when << ',' << network << ',' << location << ',' << run << ',' << x.test << ','
          << x.proto << ',' << x.direction << ',' << x.size << ',' << x.seq << ',';
        if (!std::isnan(x.ms)) f << x.ms;
        f << ',';
        if (!std::isnan(x.mbps)) f << x.mbps;
        f << ',' << x.lost << '\n';
    }
}

static int run_client(const std::string& host, uint16_t port, const std::string& network,
                      const std::string& location, int runs, const std::string& out,
                      bool quick, double udp_seconds) {
    sockaddr_in addr{};
    if (!resolve(host, port, addr)) {
        std::cerr << "Kan host niet vinden: " << host << "\n";
        return 1;
    }
    // Testsuite: berichttypes van een ROS2-zorgrobot (zie wiki, deelvraag 1).
    std::vector<TestDef> suite = {
        {"commando_20hz", true, 0, 64, 20, 0},              // cmd_vel / stopcommando
        {"sensor_10hz", true, 0, 1200, 10, 0},              // gereduceerde lidar-scan / odometrie
        {"sensor_400hz", true, 0, 1200, 400, 0},            // belasting: meerdere sensorstromen (~3,8 Mbit/s)
        {"camera_50kB", false, MODE_UPLOAD, 50000, 0, 40},  // JPEG-frame 640x480 naar server
        {"kaart_1MB", false, MODE_DOWNLOAD, 1000000, 0, quick ? 3u : 5u},  // kaart nieuwe verdieping
        {"bulk_up", false, MODE_UPLOAD, quick ? 5000000u : 10000000u, 0, quick ? 2u : 3u},
        {"bulk_down", false, MODE_DOWNLOAD, quick ? 5000000u : 10000000u, 0, quick ? 2u : 3u},
    };

    std::cout << "Robot -> " << host << ":" << port << "  netwerk=" << network
              << " locatie=" << location << " runs=" << runs << "\n";
    for (int run = 1; run <= runs; ++run) {
        std::cout << "--- run " << run << "/" << runs << " ---\n";
        for (auto& t : suite) {
            std::string when = timestamp();
            auto samples = t.udp ? udp_test(addr, t, udp_seconds) : tcp_test(addr, t);
            print_summary(t, samples);
            append_csv(out, when, network, location, run, samples);
        }
    }
    std::cout << "Klaar. Ruwe data toegevoegd aan " << out << "\n";
    return 0;
}

// ---------------------------------------------------------------- main

static std::string arg(int argc, char** argv, const std::string& key, const std::string& def) {
    for (int i = 2; i + 1 < argc; ++i)
        if (key == argv[i]) return argv[i + 1];
    return def;
}
static bool flag(int argc, char** argv, const std::string& key) {
    for (int i = 2; i < argc; ++i)
        if (key == argv[i]) return true;
    return false;
}

int main(int argc, char** argv) {
#ifdef _WIN32
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return 1;
    timeBeginPeriod(1);  // nauwkeurigere sleep voor UDP-verzendritme
#endif
    std::string cmd = argc > 1 ? argv[1] : "";
    uint16_t port = (uint16_t)std::stoi(arg(argc, argv, "--port", "5201"));
    int rc = 1;
    if (cmd == "server") {
        rc = run_server(port);
    } else if (cmd == "client") {
        std::string host = arg(argc, argv, "--host", "");
        if (host.empty()) {
            std::cerr << "--host is verplicht\n";
        } else {
            rc = run_client(host, port, arg(argc, argv, "--network", "onbekend"),
                            arg(argc, argv, "--location", "A"),
                            std::stoi(arg(argc, argv, "--runs", "3")),
                            arg(argc, argv, "--out", "metingen.csv"), flag(argc, argv, "--quick"),
                            std::stod(arg(argc, argv, "--udp-seconds", "15")));
        }
    } else {
        std::cout << "Gebruik:\n"
                     "  robotnet server [--port 5201]\n"
                     "  robotnet client --host <ip|naam> --network wifi|5g --location A\n"
                     "                  [--runs 3] [--port 5201] [--out metingen.csv]\n"
                     "                  [--quick] [--udp-seconds 15]\n";
    }
#ifdef _WIN32
    timeEndPeriod(1);
    WSACleanup();
#endif
    return rc;
}
