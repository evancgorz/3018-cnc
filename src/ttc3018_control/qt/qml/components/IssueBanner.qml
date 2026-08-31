import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var palette
    property bool active: false
    property string title: ""
    property string explanation: ""
    property var actions: []
    signal actionRequested(string action)
    visible: active
    implicitHeight: 68
    radius: 10
    color: Qt.rgba(palette.danger.r, palette.danger.g, palette.danger.b, 0.12)
    border.color: Qt.rgba(palette.danger.r, palette.danger.g, palette.danger.b, 0.48)
    border.width: 1
    RowLayout {
        anchors.fill: parent
        anchors.margins: 11
        spacing: 10
        Label { text: "!"; color: palette.danger; font.pixelSize: 21; font.bold: true }
        ColumnLayout { Layout.fillWidth: true; spacing: 2
            Label { text: root.title; color: palette.text; font.weight: Font.DemiBold }
            Label { text: root.explanation; color: palette.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true; maximumLineCount: 2; elide: Text.ElideRight }
        }
        Repeater { model: root.actions.slice(0, 2); delegate: Button { required property string modelData; text: modelData; font.pixelSize: 11; onClicked: root.actionRequested(modelData) } }
    }
}
