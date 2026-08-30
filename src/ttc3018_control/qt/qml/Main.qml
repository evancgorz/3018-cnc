import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1500
    height: 920
    minimumWidth: 1180
    minimumHeight: 720
    visible: true
    title: "TTC 3018 Control — Qt Preview"
    color: window.palette.background

    readonly property var palette: ({
        background: Qt.color("#181A1F"), surface: Qt.color("#22252B"),
        raised: Qt.color("#2B2F36"), hover: Qt.color("#343941"),
        accent: Qt.color("#168BFF"), accentHover: Qt.color("#3B9EFF"),
        text: Qt.color("#F2F4F7"), muted: Qt.color("#A8AFBA"),
        subtle: Qt.color("#737B87"), divider: Qt.color("#3A3F48"),
        warning: Qt.color("#F5B942"), danger: Qt.color("#ED5B5B"),
        success: Qt.color("#40C4D9")
    })

    property int workspace: 0
    property string toastText: ""

    Connections {
        target: appViewModel
        function onToast_requested(message) {
            window.toastText = message
            toastTimer.restart()
        }
    }

    Timer {
        id: toastTimer
        interval: 4200
        onTriggered: window.toastText = ""
    }

    component Panel: Rectangle {
        color: window.palette.surface
        radius: 12
        border.color: window.palette.divider
        border.width: 1
    }

    component Divider: Rectangle {
        Layout.fillWidth: true
        height: 1
        color: window.palette.divider
    }

    component SectionTitle: Label {
        font.pixelSize: 14
        font.weight: Font.DemiBold
        color: window.palette.text
    }

    component MutedLabel: Label {
        color: window.palette.muted
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }

    component Pill: Rectangle {
        required property string label
        required property color tone
        implicitWidth: pillLabel.implicitWidth + 18
        implicitHeight: 26
        radius: 13
        color: Qt.rgba(tone.r, tone.g, tone.b, 0.16)
        border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.42)
        border.width: 1
        Label {
            id: pillLabel
            anchors.centerIn: parent
            text: parent.label
            color: parent.tone
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }
    }

    component PrimaryButton: Button {
        id: control
        property bool dangerous: false
        implicitHeight: 38
        padding: 15
        font.pixelSize: 13
        font.weight: Font.DemiBold
        contentItem: Text {
            text: control.text
            color: window.palette.text
            font: control.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            color: control.down ? (control.dangerous ? "#B94343" : "#086FCC")
                                : control.hovered ? (control.dangerous ? "#E26A6A" : window.palette.accentHover)
                                                  : (control.dangerous ? window.palette.danger : window.palette.accent)
        }
    }

    component SecondaryButton: Button {
        id: control
        implicitHeight: 36
        padding: 13
        font.pixelSize: 12
        contentItem: Text {
            text: control.text
            color: control.enabled ? window.palette.text : window.palette.subtle
            font: control.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            color: control.down ? "#20242A" : control.hovered ? window.palette.hover : window.palette.raised
            border.width: 1
            border.color: control.enabled ? window.palette.divider : "#30343A"
        }
    }

    component Field: TextField {
        id: control
        implicitHeight: 36
        color: window.palette.text
        font.pixelSize: 13
        selectByMouse: true
        background: Rectangle {
            radius: 7
            color: "#1C1F24"
            border.color: control.activeFocus ? window.palette.accent : window.palette.divider
            border.width: control.activeFocus ? 2 : 1
        }
    }

    component StatusMetric: Item {
        id: statusMetric
        required property string name
        required property string value
        required property color tone
        implicitWidth: metricLabel.implicitWidth + 22
        implicitHeight: 44
        Column {
            anchors.centerIn: parent
            spacing: 1
            Label { text: statusMetric.name.toUpperCase(); color: window.palette.subtle; font.pixelSize: 9; font.letterSpacing: 1.1 }
            Label { id: metricLabel; text: statusMetric.value; color: statusMetric.tone; font.pixelSize: 12; font.weight: Font.DemiBold }
        }
    }

    header: Rectangle {
        height: 102
        color: window.palette.surface
        border.color: window.palette.divider
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            spacing: 2

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                spacing: 16

                Row {
                    spacing: 9
                    Rectangle { width: 25; height: 25; radius: 7; color: window.palette.accent; anchors.verticalCenter: parent.verticalCenter
                        Label { anchors.centerIn: parent; text: "T"; color: "white"; font.bold: true; font.pixelSize: 14 }
                    }
                    Label { text: "TTC 3018"; color: window.palette.text; font.pixelSize: 16; font.weight: Font.Bold; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "CONTROL"; color: window.palette.subtle; font.pixelSize: 11; font.letterSpacing: 1.5; anchors.verticalCenter: parent.verticalCenter }
                }
                Item { Layout.fillWidth: true }
                Pill { label: appViewModel.connection; tone: window.palette.warning }
                Pill { label: appViewModel.grbl_state; tone: window.palette.muted }
                SecondaryButton { text: "Connect"; onClicked: appViewModel.show_connection_notice() }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 48
                spacing: 6

                Repeater {
                    model: ["Prepare", "Preview & Run", "Machine", "Guided Setup", "Commissioning"]
                    delegate: Button {
                        required property int index
                        required property string modelData
                        text: modelData
                        checkable: true
                        checked: window.workspace === index
                        implicitWidth: index === 1 ? 130 : 112
                        implicitHeight: 40
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        onClicked: window.workspace = index
                        contentItem: Text { text: parent.text; color: parent.checked ? window.palette.text : window.palette.muted; font: parent.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        background: Rectangle { radius: 7; color: parent.checked ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.20) : parent.hovered ? window.palette.hover : "transparent"; border.color: parent.checked ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.65) : "transparent"; border.width: 1 }
                    }
                }
                Item { Layout.fillWidth: true }
                Label { text: "Qt migration preview"; color: window.palette.subtle; font.pixelSize: 11 }
            }
        }
    }

    footer: Rectangle {
        height: 54
        color: window.palette.surface
        border.color: window.palette.divider
        border.width: 1
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            spacing: 26
            StatusMetric { name: "Machine"; value: appViewModel.machine_position; tone: window.palette.text }
            StatusMetric { name: "Work"; value: appViewModel.work_position; tone: window.palette.text }
            StatusMetric { name: "Reference"; value: appViewModel.reference; tone: window.palette.warning }
            StatusMetric { name: "Work zero"; value: appViewModel.work_zero; tone: window.palette.warning }
            Item { Layout.fillWidth: true }
            StatusMetric { name: "Spindle"; value: appViewModel.spindle; tone: window.palette.muted }
        }
    }

    StackLayout {
        anchors.fill: parent
        anchors.margins: 18
        currentIndex: window.workspace

        // Prepare
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 210; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 10
                        SectionTitle { text: "Create or load" }
                        MutedLabel { text: "Start with an existing G-code file or create a centerline engraving." }
                        Divider {}
                        Repeater { model: ["Load G-code", "Text engraving", "Plaque builder"]
                            delegate: SecondaryButton { Layout.fillWidth: true; text: modelData; onClicked: appViewModel.show_preview_notice(text) }
                        }
                        Divider {}
                        SectionTitle { text: "Recent jobs" }
                        Repeater { model: ["Welcome plaque", "Air-cut test", "Text engraving"]
                            delegate: Button { Layout.fillWidth: true; text: modelData; flat: true; contentItem: Text { text: parent.text; color: parent.hovered ? window.palette.text : window.palette.muted; font.pixelSize: 12; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter } }
                        }
                        Item { Layout.fillHeight: true }
                        Label { text: "Generated jobs are validated before they can run."; color: window.palette.subtle; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 18; modeLabel: "PREPARE" }
                }
                Panel { Layout.preferredWidth: 310; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 13
                        SectionTitle { text: "Job inspector" }
                        MutedLabel { text: "Select a job source to edit its settings and see the exact centerline toolpath." }
                        Divider {}
                        Label { text: "No job selected"; color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold }
                        MutedLabel { text: "Load G-code, create text, or build a plaque. The canvas remains the single source of visual context."; Layout.fillWidth: true }
                        Item { Layout.fillHeight: true }
                        PrimaryButton { Layout.fillWidth: true; text: "Create a job"; onClicked: appViewModel.show_preview_notice(text) }
                    }
                }
            }
        }

        // Preview & Run
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 18; modeLabel: "PREVIEW"; showJob: true }
                }
                Panel { Layout.preferredWidth: 355; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 13
                        SectionTitle { text: "Preflight" }
                        Pill { label: "No validated job loaded"; tone: window.palette.warning }
                        Divider {}
                        Label { text: "Ready when verified"; color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold }
                        Repeater { model: ["Machine is connected and Idle", "Virtual reference is trusted", "XYZ work zero is confirmed", "Job fits the virtual envelope", "Material and tool are secure"]
                            delegate: RowLayout { Layout.fillWidth: true; spacing: 8
                                Rectangle { width: 17; height: 17; radius: 8.5; color: "transparent"; border.color: window.palette.subtle; border.width: 1 }
                                Label { text: modelData; color: window.palette.muted; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            }
                        }
                        Item { Layout.fillHeight: true }
                        PrimaryButton { Layout.fillWidth: true; text: "Start job"; enabled: false; opacity: 0.55 }
                        RowLayout { Layout.fillWidth: true
                            SecondaryButton { Layout.fillWidth: true; text: "Pause"; enabled: false }
                            SecondaryButton { Layout.fillWidth: true; text: "Resume"; enabled: false }
                            SecondaryButton { Layout.fillWidth: true; text: "Abort"; enabled: false }
                        }
                    }
                }
            }
        }

        // Machine
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 210; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 8
                        SectionTitle { text: "Machine" }
                        Repeater { model: ["Status", "Connection", "Machine profile", "Coordinates", "Console"]
                            delegate: SecondaryButton { Layout.fillWidth: true; text: modelData; onClicked: appViewModel.show_preview_notice(text) }
                        }
                        Item { Layout.fillHeight: true }
                        MutedLabel { text: "Reference and work zero are intentionally separate safety states." }
                    }
                }
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 18; modeLabel: "MACHINE"; showEnvelope: true }
                }
                Panel { Layout.preferredWidth: 365; Layout.minimumWidth: 365; Layout.maximumWidth: 365; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 12
                        SectionTitle { text: "Position the machine" }
                        MutedLabel { text: "Jogging remains disabled until a shared motion service is connected to this Qt workspace." }
                        RowLayout { Layout.fillWidth: true
                            Label { text: "Step"; color: window.palette.muted; font.pixelSize: 12 }
                            ComboBox { Layout.fillWidth: true; model: ["0.1 mm", "1 mm", "10 mm"]; currentIndex: 1 }
                        }
                        RowLayout { Layout.fillWidth: true
                            Label { text: "Feed"; color: window.palette.muted; font.pixelSize: 12 }
                            Field { Layout.preferredWidth: 72; text: "500"; validator: DoubleValidator {} }
                            Label { text: "mm/min"; color: window.palette.subtle; font.pixelSize: 11 }
                            Item { Layout.fillWidth: true }
                        }
                        GridLayout { Layout.alignment: Qt.AlignHCenter; columns: 3; rowSpacing: 7; columnSpacing: 7
                            Item { width: 52; height: 36 }
                            SecondaryButton { width: 52; text: "Y+"; enabled: false }
                            SecondaryButton { width: 52; text: "Z+"; enabled: false }
                            SecondaryButton { width: 52; text: "X−"; enabled: false }
                            SecondaryButton { width: 52; text: "Home"; enabled: false }
                            SecondaryButton { width: 52; text: "X+"; enabled: false }
                            Item { width: 52; height: 36 }
                            SecondaryButton { width: 52; text: "Y−"; enabled: false }
                            SecondaryButton { width: 52; text: "Z−"; enabled: false }
                        }
                        Divider {}
                        SectionTitle { text: "Move to virtual coordinates" }
                        GridLayout { Layout.fillWidth: true; columns: 2
                            Label { text: "X"; color: window.palette.muted }
                            Field { text: "0.00"; Layout.fillWidth: true }
                            Label { text: "Y"; color: window.palette.muted }
                            Field { text: "0.00"; Layout.fillWidth: true }
                            Label { text: "Z"; color: window.palette.muted }
                            Field { text: "0.00"; Layout.fillWidth: true }
                        }
                        SecondaryButton { Layout.fillWidth: true; text: "Move safely"; enabled: false }
                        Divider {}
                        Repeater { model: ["Retract to safe Z", "Return to work zero", "Return to virtual reference", "Establish reference here", "Set XYZ work zero"]
                            delegate: SecondaryButton { Layout.fillWidth: true; text: modelData; enabled: false }
                        }
                    }
                }
            }
        }

        // Guided setup
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 265; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 6
                        SectionTitle { text: "Guided setup" }
                        MutedLabel { text: "A clear, safety-gated path from connection to engraving." }
                        Divider {}
                        Repeater { model: ["1  Safety", "2  Connect", "3  Machine profile", "4  Machine reference", "5  Work zero", "6  Create or load", "7  Review", "8  Physical preflight", "9  Run"]
                            delegate: RowLayout { Layout.fillWidth: true; Layout.preferredHeight: 32; spacing: 9
                                Rectangle { width: 19; height: 19; radius: 9.5; color: index === 0 ? window.palette.accent : window.palette.raised; Label { anchors.centerIn: parent; text: index + 1; color: index === 0 ? "white" : window.palette.muted; font.pixelSize: 10; font.bold: true } }
                                Label { text: modelData.substring(3); color: index === 0 ? window.palette.text : window.palette.muted; font.pixelSize: 12; Layout.fillWidth: true }
                            }
                        }
                    }
                }
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 48; spacing: 18
                        Pill { label: "Step 1 of 9"; tone: window.palette.accent }
                        Label { text: "Start safe"; color: window.palette.text; font.pixelSize: 30; font.weight: Font.Bold }
                        Label { text: "This workspace guides a complete manual-reference engraving workflow. It keeps reference, work zero, and physical preflight distinct so that each action is clear and deliberate."; color: window.palette.muted; font.pixelSize: 16; wrapMode: Text.Wrap; Layout.maximumWidth: 680 }
                        Divider {}
                        Repeater { model: ["Keep physical power removal or an emergency stop within reach.", "Do not drive axes into mechanical stops.", "Confirm the spindle is off before reference and setup moves.", "No homing switches or probe are assumed in this workflow."]
                            delegate: RowLayout { Layout.fillWidth: true; spacing: 10
                                Rectangle { width: 19; height: 19; radius: 4; color: Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.18); Label { anchors.centerIn: parent; text: "✓"; color: window.palette.accent; font.bold: true } }
                                Label { text: modelData; color: window.palette.text; font.pixelSize: 14; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            }
                        }
                        Item { Layout.fillHeight: true }
                        RowLayout { Layout.fillWidth: true; Item { Layout.fillWidth: true } PrimaryButton { text: "Continue to connection"; onClicked: appViewModel.show_preview_notice(text) } }
                    }
                }
            }
        }

        // Commissioning
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 300; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 10
                        SectionTitle { text: "Commissioning" }
                        MutedLabel { text: "Optional hardware setup for switches, homing, limits, and a touch probe." }
                        Divider {}
                        Repeater { model: ["Inputs", "Homing", "Probe", "Summary"]
                            delegate: SecondaryButton { Layout.fillWidth: true; text: modelData; onClicked: appViewModel.show_preview_notice(text) }
                        }
                        Item { Layout.fillHeight: true }
                        Pill { label: "No commands on open"; tone: window.palette.success }
                    }
                }
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 42; spacing: 18
                        Pill { label: "Commissioning is optional"; tone: window.palette.accent }
                        Label { text: "Build trust in the machine"; color: window.palette.text; font.pixelSize: 30; font.weight: Font.Bold }
                        Label { text: "Commission switches and probe hardware in ordered, verified steps. Opening this workspace never sends a command. Motion and settings changes remain separate, confirmed actions."; color: window.palette.muted; font.pixelSize: 16; wrapMode: Text.Wrap; Layout.maximumWidth: 760 }
                        Divider {}
                        GridLayout { columns: 2; Layout.fillWidth: true; rowSpacing: 12; columnSpacing: 12
                            Repeater { model: [["1", "Test inputs", "Confirm clean press-and-release signals."], ["2", "Set homing", "Review direction, polarity, and travel."], ["3", "Verify protection", "Confirm homing before enabling limits."], ["4", "Record probe", "Store measured geometry without probe motion."]]
                                delegate: Panel { required property var modelData; Layout.fillWidth: true; Layout.preferredHeight: 124
                                    Column { anchors.fill: parent; anchors.margins: 14; spacing: 5
                                        Label { text: parent.parent.modelData[0]; color: window.palette.accent; font.pixelSize: 12; font.bold: true }
                                        Label { text: parent.parent.modelData[1]; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                        Label { text: parent.parent.modelData[2]; color: window.palette.muted; font.pixelSize: 12; wrapMode: Text.Wrap; width: parent.width }
                                    }
                                }
                            }
                        }
                        Item { Layout.fillHeight: true }
                        PrimaryButton { text: "Review input checks"; onClicked: appViewModel.show_preview_notice(text) }
                    }
                }
            }
        }
    }

    component ToolpathCanvas: Item {
        property string modeLabel: "PREVIEW"
        property bool showJob: false
        property bool showEnvelope: false

        Rectangle { anchors.fill: parent; radius: 9; color: "#1D2025"; border.color: window.palette.divider; border.width: 1 }
        Canvas {
            id: canvas
            anchors.fill: parent
            anchors.margins: 20
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                ctx.fillStyle = "#1D2025"
                ctx.fillRect(0, 0, width, height)
                const step = Math.max(24, Math.min(width, height) / 14)
                ctx.lineWidth = 1
                ctx.strokeStyle = "#30353E"
                for (let x = 0; x <= width; x += step) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke() }
                for (let y = 0; y <= height; y += step) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke() }
                const inset = Math.min(width, height) * 0.13
                ctx.strokeStyle = "#4B5867"
                ctx.lineWidth = 2
                ctx.strokeRect(inset, inset, width - inset * 2, height - inset * 2)
                if (showJob || modeLabel === "PREPARE") {
                    const l = inset + (width - inset * 2) * 0.20
                    const t = inset + (height - inset * 2) * 0.25
                    const w = (width - inset * 2) * 0.56
                    const h = (height - inset * 2) * 0.44
                    ctx.strokeStyle = "#168BFF"
                    ctx.lineWidth = 2.5
                    ctx.strokeRect(l, t, w, h)
                    ctx.beginPath()
                    ctx.moveTo(l + w * .18, t + h * .64)
                    ctx.lineTo(l + w * .82, t + h * .64)
                    ctx.moveTo(l + w * .26, t + h * .38)
                    ctx.lineTo(l + w * .74, t + h * .38)
                    ctx.stroke()
                    ctx.setLineDash([6, 5])
                    ctx.strokeStyle = "#657282"
                    ctx.beginPath(); ctx.moveTo(inset, height - inset); ctx.lineTo(l, t + h); ctx.stroke(); ctx.setLineDash([])
                }
                ctx.fillStyle = "#40C4D9"
                ctx.beginPath(); ctx.arc(inset, height - inset, 6, 0, Math.PI * 2); ctx.fill()
            }
        }
        Row { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 14; spacing: 8
            Pill { label: parent.parent.modeLabel; tone: window.palette.accent }
            Pill { visible: parent.parent.showEnvelope; label: "Virtual envelope"; tone: window.palette.warning }
        }
        Column { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 14; spacing: 6
            Repeater { model: ["Fit", "+", "−", "Top"]
                delegate: SecondaryButton { width: 52; padding: 5; text: modelData; onClicked: appViewModel.show_preview_notice(text + " view") }
            }
        }
        Row { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 14; spacing: 15
            Label { text: "● Work zero"; color: window.palette.success; font.pixelSize: 11 }
            Label { text: "— Travel envelope"; color: window.palette.muted; font.pixelSize: 11 }
            Label { text: "— Cutting path"; color: window.palette.accent; font.pixelSize: 11 }
        }
    }

    Rectangle {
        visible: window.toastText.length > 0
        z: 10
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 76
        width: Math.min(620, toastLabel.implicitWidth + 42)
        height: Math.max(46, toastLabel.implicitHeight + 24)
        radius: 9
        color: "#303640"
        border.color: window.palette.divider
        border.width: 1
        Label { id: toastLabel; anchors.centerIn: parent; width: parent.width - 32; text: window.toastText; color: window.palette.text; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 12 }
    }
}
