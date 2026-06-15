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
            height: 420,
            html: '<div id="drive-info-container" style="font-family:\'Courier New\',monospace;font-size:13px;padding:20px;color:#333;background:#fff;height:100%;box-sizing:border-box;overflow:auto;"><p id="drive-info-loading" style="color:#666;">Loading drive information...</p></div>'
        }, a));
        this.on("afterrender", this.loadDriveInfo, this);
    },
    loadDriveInfo: function() {
        Ext.Ajax.request({
            url: "/webapi/entry.cgi",
            method: "POST",
            params: {
                api: "SYNO.Core.ExternalDevice.Storage.USB",
                method: "list",
                version: 1
            },
            scope: this,
            callback: function() {
                // Fallback: just run our CGI
            }
        });
        // Fetch output from our wrapper CGI
        Ext.Ajax.request({
            url: "/webman/3rdparty/drive_info/cgi/drive_info.cgi",
            method: "GET",
            scope: this,
            success: function(response) {
                var container = Ext.get("drive-info-container");
                if (!container) { return; }
                var text = response.responseText || "";
                // Strip ANSI colour codes
                text = text.replace(/\x1b\[[0-9;]*m/g, "");
                // Build HTML table from lines
                var lines = text.split("\n");
                var html = '<h2 style="margin-top:0;font-family:Arial,sans-serif;font-size:15px;color:#333;">Drive Information</h2>';
                var inTable = false;
                var headers = null;
                var colWidths = [];
                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i];
                    // Separator line (dashes)
                    if (/^-+$/.test(line.trim())) {
                        if (!inTable) {
                            // Start of table — next non-separator line is header
                            inTable = true;
                            html += '<table style="border-collapse:collapse;width:100%;font-family:\'Courier New\',monospace;font-size:12px;">';
                        }
                        continue;
                    }
                    if (inTable && headers === null && line.trim() !== "") {
                        // Header row
                        var cols = line.trim().split(/  +/);
                        headers = cols;
                        html += "<thead><tr>";
                        for (var c = 0; c < cols.length; c++) {
                            html += '<th style="text-align:left;padding:4px 10px 4px 4px;border-bottom:2px solid #ccc;color:#555;font-family:Arial,sans-serif;font-size:12px;">' + Ext.htmlEncode(cols[c]) + "</th>";
                        }
                        html += "</tr></thead><tbody>";
                        continue;
                    }
                    if (inTable && headers !== null && line.trim() !== "") {
                        // Data row — split on 2+ spaces
                        var cells = line.trim().split(/  +/);
                        var isFirst = true;
                        html += "<tr>";
                        for (var c = 0; c < headers.length; c++) {
                            var val = cells[c] !== undefined ? cells[c] : "";
                            var style = 'padding:4px 10px 4px 4px;border-bottom:1px solid #eee;';
                            if (c === 1) {
                                // Drive Number column — cyan highlight
                                style += 'color:#0073c0;font-weight:bold;';
                            } else if (c === 3) {
                                // Serial column — amber highlight
                                style += 'color:#b5800a;';
                            }
                            html += '<td style="' + style + '">' + Ext.htmlEncode(val) + "</td>";
                        }
                        html += "</tr>";
                        continue;
                    }
                    if (inTable && line.trim() === "" && headers !== null) {
                        // Blank line ends this table section
                        html += "</tbody></table><br>";
                        inTable = false;
                        headers = null;
                        continue;
                    }
                    if (!inTable && line.trim() !== "") {
                        html += '<p style="font-family:Arial,sans-serif;font-size:12px;color:#c00;">' + Ext.htmlEncode(line) + "</p>";
                    }
                }
                if (inTable) { html += "</tbody></table>"; }
                container.update(html);
            },
            failure: function(response) {
                var container = Ext.get("drive-info-container");
                if (!container) { return; }
                container.update('<p style="color:#c00;font-family:Arial,sans-serif;">Failed to retrieve drive information (HTTP ' + response.status + ').<br>Check that the package is running and that the CGI script has execute permission.</p><p style="font-family:Arial,sans-serif;font-size:12px;color:#888;">CGI path: /webman/3rdparty/drive_info/cgi/drive_info.cgi</p>');
            }
        });
    },
    onClose: function() {
        SYNO.SDS.drive_info.MainWindow.superclass.onClose.apply(this, arguments);
        this.doClose();
        return true;
    }
});
