import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var palette: ({ accent: "#0A84FF", text: "#F5F5F7", muted: "#AEAEB2" })
    readonly property color accentColor: palette && palette.accent ? palette.accent : "#0A84FF"
    readonly property color textColor: palette && palette.text ? palette.text : "#F5F5F7"
    readonly property color mutedColor: palette && palette.muted ? palette.muted : "#AEAEB2"
    property bool active: false
    property string name: ""
    property string phase: ""
    property real progress: 0
    visible: active
    implicitHeight: 38
    radius: 12
    color: Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.10)
    border.color: Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.30)
    border.width: 1
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 13
        anchors.rightMargin: 13
        spacing: 10
        BusyIndicator { running: root.active; implicitWidth: 18; implicitHeight: 18 }
        Label { text: root.name; color: root.textColor; font.weight: Font.DemiBold }
        Label { text: root.phase; color: root.mutedColor; Layout.fillWidth: true; elide: Text.ElideRight }
        ProgressBar { visible: root.progress > 0; from: 0; to: 1; value: root.progress; Layout.preferredWidth: 120 }
    }
}
