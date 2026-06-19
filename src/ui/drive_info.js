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
            width: 800,
            height: 440,
            html: '<iframe src="webman/3rdparty/drive_info/api.cgi?_ts=' + new Date().getTime() + '" style="width:100%;height:100%;border:none;margin:0;"></iframe>'
        }, a));
    },
    onClose: function() {
        SYNO.SDS.drive_info.MainWindow.superclass.onClose.apply(this, arguments);
        this.doClose();
        return true;
    }
});
