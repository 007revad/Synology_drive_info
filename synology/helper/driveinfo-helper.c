/*
 * driveinfo-helper.c
 *
 * Narrow setuid-root launcher for Synology_drive_info.
 * Installed by DSM owner root:<package>, mode 6550 (setuid), from conf/privilege.
 *
 * Replaces the sudoers-based escalation (drive_info sudoers rules):
 * does not depend on /usr/bin/sudo being present, and only ever
 * executes one of four fixed, hardcoded script paths, each with a
 * whitelisted, fixed-shape set of arguments mirroring what the old
 * sudoers rules allowed.
 *
 * Usage:
 *   driveinfo-helper drive_info           [ARG]
 *   driveinfo-helper smart_info           ARG1 [ARG2]
 *   driveinfo-helper check_ip_port        ARG1 ARG2
 *   driveinfo-helper smart_passive_info   ARG1 [ARG2]
 *   driveinfo-helper task_scheduler create NAME CMD NOTIFY_ENABLE NOTIFY_ERROR_ONLY EMAIL
 *   driveinfo-helper task_scheduler delete TASK_ID OWNER
 *   driveinfo-helper task_scheduler delete_by_name NAME
 *   driveinfo-helper task_scheduler list
 */

#define _GNU_SOURCE
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

#define SCRIPT_DIR "/var/packages/drive_info/target/ui/bin"

#define DRIVE_INFO_SCRIPT      SCRIPT_DIR "/drive_info.sh"
#define SMART_INFO_SCRIPT      SCRIPT_DIR "/smart_info.sh"
#define CHECK_IP_PORT_SCRIPT   SCRIPT_DIR "/check_ip_port.sh"
#define SMART_PASSIVE_SCRIPT   SCRIPT_DIR "/smart_passive_info.sh"
#define TASK_SCHEDULER_SCRIPT  SCRIPT_DIR "/task_scheduler.sh"

/* The fixed task name api.cgi always creates the schedule under. */
#define SCHEDULE_TASK_NAME "Drive Info SMART Schedule"

static int starts_with(const char *s, const char *prefix)
{
    return strncmp(s, prefix, strlen(prefix)) == 0;
}

/* --dev=/dev/<prefix>* — prefix must be one of a fixed allow-list.
 * smart_info.sh (active node) allowed sd, hd, sata, sas, nvme, nvc, usb
 * per the old sudoers rules.
 */
static int valid_dev_arg_active(const char *s)
{
    static const char *prefixes[] = { "sd", "hd", "sata", "sas", "nvme", "nvc", "usb", NULL };
    const char *base = "--dev=/dev/";
    size_t blen = strlen(base);
    if (!starts_with(s, base)) return 0;
    const char *dev = s + blen;
    for (int i = 0; prefixes[i] != NULL; i++)
        if (starts_with(dev, prefixes[i])) return 1;
    return 0;
}

/* smart_passive_info.sh (passive/HA node) only ever allowed sd, sata, sas,
 * nvme per the old sudoers rules — narrower than the active-node script.
 */
static int valid_dev_arg_passive(const char *s)
{
    static const char *prefixes[] = { "sd", "sata", "sas", "nvme", NULL };
    const char *base = "--dev=/dev/";
    size_t blen = strlen(base);
    if (!starts_with(s, base)) return 0;
    const char *dev = s + blen;
    for (int i = 0; prefixes[i] != NULL; i++)
        if (starts_with(dev, prefixes[i])) return 1;
    return 0;
}

static int is_bool_str(const char *s)
{
    return strcmp(s, "true") == 0 || strcmp(s, "false") == 0;
}

static int all_digits(const char *s)
{
    if (*s == '\0') return 0;
    for (; *s; s++)
        if (*s < '0' || *s > '9') return 0;
    return 1;
}

/* Task Scheduler owner is always stored as "root" by api.cgi, but be
 * a little permissive on shape (username-like) rather than an exact
 * literal, in case that ever changes. */
static int valid_owner(const char *s)
{
    if (*s == '\0') return 0;
    for (const char *p = s; *p; p++)
        if (!isalnum((unsigned char)*p) && *p != '_') return 0;
    return 1;
}

/* Minimal shape check mirroring api.cgi's own email regex
 * (^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$) - just enough to
 * reject anything that couldn't have come from that validation. */
static int valid_email(const char *s)
{
    const char *at = strchr(s, '@');
    if (!at || at == s) return 0;
    if (strchr(at + 1, '@')) return 0;
    for (const char *p = s; *p; p++)
        if (isspace((unsigned char)*p)) return 0;
    const char *dot = strrchr(at, '.');
    if (!dot || dot == at + 1 || *(dot + 1) == '\0') return 0;
    return 1;
}

/* api.cgi only ever schedules smart_info.sh with one of these three
 * exact flag combinations - see api.cgi's _smart_script_cmd logic. */
static int valid_schedule_cmd(const char *s)
{
    static const char *allowed[] = {
        SMART_INFO_SCRIPT " -e -i",
        SMART_INFO_SCRIPT " -e",
        SMART_INFO_SCRIPT " -e -a",
        NULL
    };
    for (int i = 0; allowed[i] != NULL; i++)
        if (strcmp(s, allowed[i]) == 0) return 1;
    return 0;
}

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "driveinfo-helper: missing subcommand\n");
        return 1;
    }

    const char *sub = argv[1];
    const char *script = NULL;
    const char *exec_argv[8] = { NULL };
    int n = 0;

    if (strcmp(sub, "drive_info") == 0) {
        /* drive_info.sh [ARG] — 0 or 1 extra argument (language code,
         * get_ha_passive, etc.). Passed through as-is via execv, so
         * there is no shell to inject into. */
        if (argc != 2 && argc != 3) {
            fprintf(stderr, "driveinfo-helper: drive_info takes 0 or 1 argument\n");
            return 1;
        }
        script = DRIVE_INFO_SCRIPT;
        exec_argv[n++] = script;
        if (argc == 3) exec_argv[n++] = argv[2];
    }
    else if (strcmp(sub, "smart_info") == 0) {
        /* smart_info.sh --dev=X                (1 arg)
         * smart_info.sh -i|-a|-ia --dev=X       (2 args)          */
        if (argc == 3) {
            if (!valid_dev_arg_active(argv[2])) {
                fprintf(stderr, "driveinfo-helper: rejected smart_info arg\n");
                return 1;
            }
            script = SMART_INFO_SCRIPT;
            exec_argv[n++] = script;
            exec_argv[n++] = argv[2];
        } else if (argc == 4) {
            if (strcmp(argv[2], "-i") != 0 && strcmp(argv[2], "-a") != 0 &&
                strcmp(argv[2], "-ia") != 0) {
                fprintf(stderr, "driveinfo-helper: rejected smart_info flag\n");
                return 1;
            }
            if (!valid_dev_arg_active(argv[3])) {
                fprintf(stderr, "driveinfo-helper: rejected smart_info arg\n");
                return 1;
            }
            script = SMART_INFO_SCRIPT;
            exec_argv[n++] = script;
            exec_argv[n++] = argv[2];
            exec_argv[n++] = argv[3];
        } else {
            fprintf(stderr, "driveinfo-helper: smart_info takes 1 or 2 arguments\n");
            return 1;
        }
    }
    else if (strcmp(sub, "check_ip_port") == 0) {
        /* check_ip_port.sh --ip=X --port=Y — exactly 2 args */
        if (argc != 4) {
            fprintf(stderr, "driveinfo-helper: check_ip_port takes 2 arguments\n");
            return 1;
        }
        if (!starts_with(argv[2], "--ip=") || argv[2][5] == '\0') {
            fprintf(stderr, "driveinfo-helper: rejected check_ip_port ip arg\n");
            return 1;
        }
        if (!starts_with(argv[3], "--port=")) {
            fprintf(stderr, "driveinfo-helper: rejected check_ip_port port arg\n");
            return 1;
        }
        const char *port = argv[3] + strlen("--port=");
        if (*port == '\0') {
            fprintf(stderr, "driveinfo-helper: rejected check_ip_port port arg\n");
            return 1;
        }
        for (const char *p = port; *p; p++) {
            if (*p < '0' || *p > '9') {
                fprintf(stderr, "driveinfo-helper: rejected check_ip_port port arg\n");
                return 1;
            }
        }
        script = CHECK_IP_PORT_SCRIPT;
        exec_argv[n++] = script;
        exec_argv[n++] = argv[2];
        exec_argv[n++] = argv[3];
    }
    else if (strcmp(sub, "smart_passive_info") == 0) {
        /* smart_passive_info.sh --dev=X        (1 arg)
         * smart_passive_info.sh -a --dev=X      (2 args)          */
        if (argc == 3) {
            if (!valid_dev_arg_passive(argv[2])) {
                fprintf(stderr, "driveinfo-helper: rejected smart_passive_info arg\n");
                return 1;
            }
            script = SMART_PASSIVE_SCRIPT;
            exec_argv[n++] = script;
            exec_argv[n++] = argv[2];
        } else if (argc == 4) {
            if (strcmp(argv[2], "-a") != 0) {
                fprintf(stderr, "driveinfo-helper: rejected smart_passive_info flag\n");
                return 1;
            }
            if (!valid_dev_arg_passive(argv[3])) {
                fprintf(stderr, "driveinfo-helper: rejected smart_passive_info arg\n");
                return 1;
            }
            script = SMART_PASSIVE_SCRIPT;
            exec_argv[n++] = script;
            exec_argv[n++] = argv[2];
            exec_argv[n++] = argv[3];
        } else {
            fprintf(stderr, "driveinfo-helper: smart_passive_info takes 1 or 2 arguments\n");
            return 1;
        }
    }
    else if (strcmp(sub, "task_scheduler") == 0) {
        /* task_scheduler create NAME CMD NOTIFY_ENABLE NOTIFY_ERROR_ONLY EMAIL  (5 args)
         * task_scheduler delete TASK_ID OWNER                                  (2 args)
         * task_scheduler delete_by_name NAME                                   (1 arg)
         * task_scheduler list                                                  (0 args)  */
        if (argc < 3) {
            fprintf(stderr, "driveinfo-helper: task_scheduler requires an action\n");
            return 1;
        }
        const char *ts_action = argv[2];

        if (strcmp(ts_action, "create") == 0) {
            if (argc != 8) {
                fprintf(stderr, "driveinfo-helper: task_scheduler create takes 5 arguments\n");
                return 1;
            }
            const char *name = argv[3], *cmd = argv[4], *notify_enable = argv[5],
                       *notify_error_only = argv[6], *email = argv[7];
            if (strcmp(name, SCHEDULE_TASK_NAME) != 0) {
                fprintf(stderr, "driveinfo-helper: rejected task_scheduler create name\n");
                return 1;
            }
            if (!valid_schedule_cmd(cmd)) {
                fprintf(stderr, "driveinfo-helper: rejected task_scheduler create cmd\n");
                return 1;
            }
            if (!is_bool_str(notify_enable) || !is_bool_str(notify_error_only)) {
                fprintf(stderr, "driveinfo-helper: rejected task_scheduler create flags\n");
                return 1;
            }
            if (!valid_email(email)) {
                fprintf(stderr, "driveinfo-helper: rejected task_scheduler create email\n");
                return 1;
            }
            script = TASK_SCHEDULER_SCRIPT;
            exec_argv[n++] = script;
            exec_argv[n++] = ts_action;
            exec_argv[n++] = name;
            exec_argv[n++] = cmd;
            exec_argv[n++] = notify_enable;
            exec_argv[n++] = notify_error_only;
            exec_argv[n++] = email;
        }
        else if (strcmp(ts_action, "delete") == 0) {
            if (argc != 5) {
                fprintf(stderr, "driveinfo-helper: task_scheduler delete takes 2 arguments\n");
                return 1;
            }
            if (!all_digits(argv[3])) {
                fprintf(stderr, "driveinfo-helper: rejected task_scheduler delete task_id\n");
                return 1;
            }
            if (!valid_owner(argv[4])) {
                fprintf(stderr, "driveinfo-helper: rejected task_scheduler delete owner\n");
                return 1;
            }
            script = TASK_SCHEDULER_SCRIPT;
            exec_argv[n++] = script;
            exec_argv[n++] = ts_action;
            exec_argv[n++] = argv[3];
            exec_argv[n++] = argv[4];
        }
        else if (strcmp(ts_action, "delete_by_name") == 0) {
            /* Only the one fixed task name is ever accepted; the name ->
             * id lookup happens inside task_scheduler.sh as root. */
            if (argc != 4) {
                fprintf(stderr, "driveinfo-helper: task_scheduler delete_by_name takes 1 argument\n");
                return 1;
            }
            if (strcmp(argv[3], SCHEDULE_TASK_NAME) != 0) {
                fprintf(stderr, "driveinfo-helper: rejected task_scheduler delete_by_name name\n");
                return 1;
            }
            script = TASK_SCHEDULER_SCRIPT;
            exec_argv[n++] = script;
            exec_argv[n++] = ts_action;
            exec_argv[n++] = argv[3];
        }
        else if (strcmp(ts_action, "list") == 0) {
            if (argc != 3) {
                fprintf(stderr, "driveinfo-helper: task_scheduler list takes no arguments\n");
                return 1;
            }
            script = TASK_SCHEDULER_SCRIPT;
            exec_argv[n++] = script;
            exec_argv[n++] = ts_action;
        }
        else {
            fprintf(stderr, "driveinfo-helper: unknown task_scheduler action '%s'\n", ts_action);
            return 1;
        }
    }
    else {
        fprintf(stderr, "driveinfo-helper: unknown subcommand '%s'\n", sub);
        return 1;
    }

    /* setuid binary gives us euid=0; promote ruid too so the exec'd
     * script is genuinely root, not just effectively root. */
    if (setuid(0) != 0) {
        perror("driveinfo-helper: setuid(0) failed");
        return 1;
    }

    /* Sanitize environment: fixed PATH, no inherited surprises. */
    if (clearenv() != 0) {
        fprintf(stderr, "driveinfo-helper: clearenv failed\n");
        return 1;
    }
    setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/usr/syno/bin:/usr/syno/sbin", 1);
    setenv("HOME", "/root", 1);

    exec_argv[n] = NULL;
    execv(script, (char *const *)exec_argv);

    perror("driveinfo-helper: execv failed");
    return 1;
}
