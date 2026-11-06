import QtQuick
import QtQuick.Controls

CheckBox {
    id: root
    required property var palette
    spacing: 10
    implicitHeight: 30

    indicator: Rectangle {
        implicitWidth: 20
        implicitHeight: 20
        x: root.leftPadding
        y: Math.round((root.height - height) / 2)
        radius: 6
        color: root.checked ? root.palette.accent : root.palette.raised
        border.width: root.activeFocus ? 2 : 1
        border.color: root.activeFocus ? root.palette.accentHover : (root.checked ? root.palette.accent : root.palette.divider)

        Text {
            anchors.centerIn: parent
            text: "✓"
            color: "white"
            visible: root.checked
            font.pixelSize: 13
            font.weight: Font.Bold
        }
    }

    contentItem: Text {
        leftPadding: root.indicator.width + root.spacing
        text: root.text
        color: root.enabled ? root.palette.text : root.palette.subtle
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
