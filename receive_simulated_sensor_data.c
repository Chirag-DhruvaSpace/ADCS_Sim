/* Receive raw sensor JSON from Python on 127.0.0.1:5005.
 * main() starts the listener. receive_sensor_data() reads complete lines.
 * print_sensor_json() contains the single sensor-data print statement.
 */
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <winsock2.h>
typedef SOCKET NetworkSocket;
#define CLOSE_SOCKET closesocket
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
typedef int NetworkSocket;
#define INVALID_SOCKET (-1)
#define SOCKET_ERROR (-1)
#define CLOSE_SOCKET close
#endif

#define SENSOR_PORT 5005
#define MAX_JSON_LENGTH (1024 * 1024)

static int start_networking(void)
{
#ifdef _WIN32
    WSADATA windows_network;
    return WSAStartup(MAKEWORD(2, 2), &windows_network) == 0;
#else
    return 1;
#endif
}

static void stop_networking(void)
{
#ifdef _WIN32
    WSACleanup();
#endif
}

static NetworkSocket open_sensor_listener(void)
{
    NetworkSocket listener;
    struct sockaddr_in address;
    int allow_address_reuse = 1;

    listener = socket(AF_INET, SOCK_STREAM, 0);
    if (listener == INVALID_SOCKET) return INVALID_SOCKET;
    setsockopt(listener, SOL_SOCKET, SO_REUSEADDR,
               (const char *)&allow_address_reuse, sizeof(allow_address_reuse));
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons(SENSOR_PORT);

    if (bind(listener, (struct sockaddr *)&address, sizeof(address)) == SOCKET_ERROR) {
        fprintf(stderr, "Cannot open port %d. Another receiver may be running.\n", SENSOR_PORT);
        CLOSE_SOCKET(listener);
        return INVALID_SOCKET;
    }
    if (listen(listener, 1) == SOCKET_ERROR) {
        fprintf(stderr, "Cannot listen for Python.\n");
        CLOSE_SOCKET(listener);
        return INVALID_SOCKET;
    }
    return listener;
}

static void print_sensor_json(const char *json_text)
{
    /* This is the sensor-data print. JSON is already readable text. */
    printf("%s\n", json_text);
    fflush(stdout);
}

static void receive_sensor_data(NetworkSocket python_connection)
{
    char received_bytes[4096];
    /* Static storage avoids putting a one-megabyte array on the Windows stack. */
    static char json_line[MAX_JSON_LENGTH + 1];
    int line_length = 0;
    int discard_long_line = 0;
    int bytes_received;
    int byte_index;

    while ((bytes_received = recv(python_connection, received_bytes, sizeof(received_bytes), 0)) > 0) {
        /* TCP may split a JSON line or combine several lines in one read. */
        for (byte_index = 0; byte_index < bytes_received; byte_index++) {
            char received_character = received_bytes[byte_index];
            if (received_character == '\n') {
                if (!discard_long_line && line_length > 0) {
                    json_line[line_length] = '\0';
                    print_sensor_json(json_line);
                }
                line_length = 0;
                discard_long_line = 0;
                continue;
            }
            if (discard_long_line) continue;
            if (line_length == MAX_JSON_LENGTH) {
                fprintf(stderr, "Sensor JSON line is too long; skipping it.\n");
                discard_long_line = 1;
                continue;
            }
            json_line[line_length++] = received_character;
        }
    }
    if (bytes_received == SOCKET_ERROR)
        fprintf(stderr, "Python connection ended with a socket error.\n");
}

int main(void)
{
    NetworkSocket listener;
    NetworkSocket python_connection;

    if (!start_networking()) {
        fprintf(stderr, "Cannot start networking.\n");
        return 1;
    }
    listener = open_sensor_listener();
    if (listener == INVALID_SOCKET) {
        stop_networking();
        return 1;
    }
    printf("Listening on 127.0.0.1:%d. Start the simulation whenever ready.\n", SENSOR_PORT);
    for (;;) {
        printf("Waiting for Python...\n");
        fflush(stdout);
        python_connection = accept(listener, NULL, NULL);
        if (python_connection == INVALID_SOCKET) break;
        printf("Python connected. Raw sensor JSON follows:\n");
        receive_sensor_data(python_connection);
        CLOSE_SOCKET(python_connection);
        printf("Python disconnected.\n");
    }
    CLOSE_SOCKET(listener);
    stop_networking();
    return 0;
}
