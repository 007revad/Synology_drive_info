Ext.namespace("SYNO.SDS.drive_info");
Ext.define("SYNO.SDS._ThirdParty.App.drive_info", {
    extend: "SYNO.SDS.AppInstance",
    appWindowName: "SYNO.SDS.drive_info.MainWindow",
    constructor: function() {
        this.callParent(arguments);
    }
});
Ext.define("SYNO.SDS.drive_info.MainWindow", {
    extend: "SYNO.SDS.AppWindow",
    constructor: function(a) {
        this.appInstance = a.appInstance;
        SYNO.SDS.drive_info.MainWindow.superclass.constructor.call(this, Ext.apply({
            layout: "fit",
            resizable: true,
            cls: "syno-app-win",
            maximizable: true,
            minimizable: true,
            showHelp: false,
            width: 700,
            height: 440,
            html: [
                '<div id="drive-info-container" style="',
                    'font-family:Arial,sans-serif;',
                    'font-size:13px;',
                    'padding:20px;',
                    'color:#333;',
                    'background:#fff;',
                    'height:100%;',
                    'box-sizing:border-box;',
                    'overflow:auto;',
                '">',
                    '<p id="drive-info-status" style="color:#666;">Loading drive information...</p>',
                '</div>'
            ].join("")
        }, a));
        this.on("afterrender", this.loadDriveInfo, this);
    },

    loadDriveInfo: function() {
        var me = this;
        var apiUrl = "/webman/3rdparty/drive_info/api.cgi";

        fetch(apiUrl, { method: "GET", credentials: "same-origin" })
            .then(function(resp) {
                if (!resp.ok) {
                    throw new Error("HTTP " + resp.status);
                }
                return resp.json();
            })
            .then(function(data) {
                me.renderResult(data);
            })
            .catch(function(err) {
                me.renderError("Failed to contact api.cgi: " + err.message);
            });
    },

    renderResult: function(data) {
        var container = document.getElementById("drive-info-container");
        if (!container) { return; }

        if (!data.success) {
            if (data.error === "no_sudoers") {
                container.innerHTML = [
                    '<h2 style="margin-top:0;color:#c00;">Permissions not configured</h2>',
                    '<p>This package needs elevated permissions to read drive information.</p>',
                    '<p>To set the required permissions, connect to your NAS via SSH and run:</p>',
                    '<pre style="',
                        'background:#f4f4f4;',
                        'border:1px solid #ddd;',
                        'border-radius:4px;',
                        'padding:12px;',
                        'font-size:12px;',
                        'line-height:1.6;',
                        'white-space:pre-wrap;',
                        'word-break:break-all;',
                    '">',
                    'sudo -i\n',
                    'echo "drive_info ALL=(root) NOPASSWD: /var/packages/drive_info/target/bin/drive_info.sh" \\\n',
                    '    > /etc/sudoers.d/drive_info\n',
                    'chmod 0440 /etc/sudoers.d/drive_info',
                    '</pre>',
                    '<p>Then close and reopen this window.</p>',
                    '<p>See <a href="https://github.com/007revad/Synology_drive_info/blob/main/set_package_permissions.md" ',
                        'target="_blank">set_package_permissions.md</a> for full details.</p>'
                ].join("");
                return;
            }
            if (data.error === "no_script") {
                container.innerHTML = '<p style="color:#c00;">drive_info.sh not found at expected path. Try reinstalling the package.</p>';
                return;
            }
            container.innerHTML = '<p style="color:#c00;">Error running drive_info.sh' +
                (data.detail ? ':<br><pre>' + this.escHtml(data.detail) + '</pre>' : '.') + '</p>';
            return;
        }

        // Parse plain-text table output into HTML
        var lines = (data.output || "").split("\n");
        var html = "";
        var inTable = false;
        var headers = null;

        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];

            // Separator line
            if (/^-+$/.test(line.trim())) {
                if (!inTable) {
                    inTable = true;
                    html += '<table style="border-collapse:collapse;width:100%;font-family:\'Courier New\',monospace;font-size:12px;margin-bottom:16px;">';
                }
                continue;
            }

            if (inTable && headers === null && line.trim() !== "") {
                headers = line.trim().split(/  +/);
                html += "<thead><tr>";
                for (var c = 0; c < headers.length; c++) {
                    html += '<th style="text-align:left;padding:5px 14px 5px 5px;border-bottom:2px solid #ccc;color:#555;font-family:Arial,sans-serif;font-size:12px;">' +
                        this.escHtml(headers[c]) + "</th>";
                }
                html += "</tr></thead><tbody>";
                continue;
            }

            if (inTable && headers !== null && line.trim() !== "") {
                var cells = line.trim().split(/  +/);
                html += "<tr>";
                for (var c = 0; c < headers.length; c++) {
                    var val = cells[c] !== undefined ? cells[c] : "";
                    var style = "padding:5px 14px 5px 5px;border-bottom:1px solid #eee;";
                    if (c === 1) { style += "color:#0073c0;font-weight:bold;"; }   // Number
                    if (c === 3) { style += "color:#b5800a;"; }                    // Serial
                    html += '<td style="' + style + '">' + this.escHtml(val) + "</td>";
                }
                html += "</tr>";
                continue;
            }

            if (inTable && line.trim() === "" && headers !== null) {
                html += "</tbody></table>";
                inTable = false;
                headers = null;
                continue;
            }
        }
        if (inTable) { html += "</tbody></table>"; }

        if (html === "") {
            html = '<p style="color:#888;">No drives found.</p>';
        }

        container.innerHTML = '<h2 style="margin-top:0;font-size:15px;color:#333;">Drive Information</h2>' + html;
    },

    renderError: function(msg) {
        var container = document.getElementById("drive-info-container");
        if (!container) { return; }
        container.innerHTML = '<p style="color:#c00;">' + this.escHtml(msg) + '</p>';
    },

    escHtml: function(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    },

    onClose: function() {
        SYNO.SDS.drive_info.MainWindow.superclass.onClose.apply(this, arguments);
        this.doClose();
        return true;
    }
});
