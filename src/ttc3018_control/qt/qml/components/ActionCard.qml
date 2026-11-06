import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    required property var palette
    required property string title
    property string description: ""
    signal triggered()
    implicitHeight: 88
    radius: 16
    color: palette.surface
    border.color: mouse.containsMouse ? palette.accent : Qt.rgba(1, 1, 1, 0.10)
    border.width: 1
    Column {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 6
        Label { text: root.title; color: palette.text; font.pixelSize: 14; font.weight: Font.DemiBold }
        Label { text: root.description; color: palette.muted; font.pixelSize: 12; lineHeight: 1.12; wrapMode: Text.Wrap; width: parent.width }
    }
    MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; onClicked: root.triggered() }
}
