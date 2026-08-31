import QtQuick
import QtQuick.Controls

Label {
    property bool valid: true
    property string message: ""
    visible: !valid && message.length > 0
    text: message
    color: "#F5B942"
    font.pixelSize: 11
    wrapMode: Text.Wrap
}
