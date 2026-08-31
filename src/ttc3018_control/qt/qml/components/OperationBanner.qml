import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var palette
    property bool active: false
    property string name: ""
    property string phase: ""
    property real progress: 0
    visible: active
    implicitHeight: 38
    radius: 9
    color: Qt.rgba(palette.accent.r, palette.accent.g, palette.accent.b, 0.12)
    border.color: Qt.rgba(palette.accent.r, palette.accent.g, palette.accent.b, 0.42)
    border.width: 1
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 13
        anchors.rightMargin: 13
        spacing: 10
        BusyIndicator { running: root.active; implicitWidth: 18; implicitHeight: 18 }
        Label { text: root.name; color: palette.text; font.weight: Font.DemiBold }
        Label { text: root.phase; color: palette.muted; Layout.fillWidth: true; elide: Text.ElideRight }
        ProgressBar { visible: root.progress > 0; from: 0; to: 1; value: root.progress; Layout.preferredWidth: 120 }
    }
}
