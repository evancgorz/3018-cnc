import QtQuick
import QtQuick.Controls

Button {
    id: root
    required property var palette
    property bool actionEnabled: true
    property string idleText: ""
    property string busyText: "Working…"
    property bool busy: false
    property bool dangerous: false
    implicitHeight: 38
    enabled: actionEnabled && !busy
    text: busy ? busyText : idleText
    contentItem: Row {
        spacing: 8
        anchors.centerIn: parent
        BusyIndicator { visible: root.busy; running: root.busy; implicitWidth: 16; implicitHeight: 16 }
        Text { text: root.text; color: root.palette.text; font: root.font; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
    }
    background: Rectangle {
        radius: 9
        color: root.down ? (root.dangerous ? "#B94343" : "#086FCC")
            : root.hovered ? (root.dangerous ? "#E26A6A" : root.palette.accentHover)
            : (root.dangerous ? root.palette.danger : root.palette.accent)
        opacity: root.enabled ? 1 : 0.5
    }
}
