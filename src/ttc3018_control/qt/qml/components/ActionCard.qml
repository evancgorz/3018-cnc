import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    required property var palette
    required property string title
    property string description: ""
    signal triggered()
    implicitHeight: 82
    radius: 10
    color: palette.surface
    border.color: mouse.containsMouse ? palette.accent : palette.divider
    border.width: 1
    Column {
        anchors.fill: parent
        anchors.margins: 13
        spacing: 5
        Label { text: root.title; color: palette.text; font.weight: Font.DemiBold }
        Label { text: root.description; color: palette.muted; font.pixelSize: 11; wrapMode: Text.Wrap; width: parent.width }
    }
    MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; onClicked: root.triggered() }
}
