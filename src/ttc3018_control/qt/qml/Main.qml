import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs as PlatformDialogs
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

    property int workspace: 2
    property string toastText: ""
    property string selectedTransport: "USB serial"
    property bool exitBypass: false

    onClosing: function(closeEvent) {
        if (exitBypass) {
            exitBypass = false
            return
        }
        if (appViewModel && appViewModel.requires_exit_prompt) {
            closeEvent.accepted = false
            exitDialog.open()
        }
    }

    Connections {
        target: appViewModel
        function onToast_requested(message) {
            window.toastText = message
            toastTimer.restart()
        }
        function onUnreferenced_jog_requested() { unreferencedJogDialog.open() }
        function onClose_requested() { window.exitBypass = true; window.close() }
    }

    Dialog {
        id: exitDialog
        modal: true
        title: "Machine is not at reference"
        width: 560
        height: 320
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Label { text: "The controller is still away from the trusted reference position."; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
            MutedLabel { text: "Returning first raises Z, moves X/Y to virtual zero, then lowers Z to reference. This uses the configured jog speed and is available only while GRBL is Idle." }
            Label { text: appViewModel ? "Current: " + appViewModel.machine_position : ""; color: window.palette.muted; font.family: "Cascadia Mono" }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: exitDialog.close() }
                SecondaryButton { text: "Close without moving"; onClicked: { window.exitBypass = true; exitDialog.close(); window.close() } }
                PrimaryButton { text: "Move to reference, then close"; enabled: appViewModel && appViewModel.can_return_to_reference; onClicked: { appViewModel.return_to_reference_and_close(); exitDialog.close() } }
            }
        }
    }

    Dialog {
        id: unreferencedJogDialog
        modal: true
        title: "Manual positioning acknowledgement"
        width: 510
        height: 270
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Label { text: "The virtual machine reference has not been established."; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
            MutedLabel { text: "Unreferenced jogs are allowed only after you confirm that you are watching the machine, moving slowly, and will stop before a physical limit. Software envelope checks are inactive until a reference is saved." }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: unreferencedJogDialog.close() }
                PrimaryButton { text: "I will jog carefully"; onClicked: { appViewModel.acknowledge_unreferenced_jog(); unreferencedJogDialog.close() } }
            }
        }
    }

    Timer {
        id: toastTimer
        interval: 4200
        onTriggered: window.toastText = ""
    }

    Dialog {
        id: connectionDialog
        modal: true
        title: "Connect to controller"
        width: 460
        height: 360
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 12
            Label { text: "Choose how TTC 3018 should reach GRBL."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: "Transport"; color: window.palette.subtle; font.pixelSize: 11 }
            ComboBox { id: transportCombo; Layout.fillWidth: true; model: ["USB serial", "Wi-Fi TCP"]; currentIndex: appViewModel && appViewModel.preferred_transport === "Wi-Fi TCP" ? 1 : 0; onActivated: window.selectedTransport = currentText }

            ColumnLayout {
                visible: transportCombo.currentText === "USB serial"
                Layout.fillWidth: true
                spacing: 7
                Label { text: "Serial port"; color: window.palette.subtle; font.pixelSize: 11 }
                RowLayout {
                    Layout.fillWidth: true
                    ComboBox { id: portCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.ports : []; currentIndex: 0 }
                    SecondaryButton { text: "Refresh"; onClicked: appViewModel.refresh_ports() }
                }
            }

            ColumnLayout {
                visible: transportCombo.currentText === "Wi-Fi TCP"
                Layout.fillWidth: true
                spacing: 7
                Label { text: "Controller address"; color: window.palette.subtle; font.pixelSize: 11 }
                RowLayout {
                    Layout.fillWidth: true
                    Field { id: wifiHostField; Layout.fillWidth: true; text: appViewModel ? appViewModel.saved_wifi_host : "192.168.4.1"; placeholderText: "IP address or host name" }
                    Field { id: wifiPortField; Layout.preferredWidth: 82; text: appViewModel ? String(appViewModel.saved_wifi_port) : "23"; validator: IntValidator { bottom: 1; top: 65535 } }
                }
                MutedLabel { text: "You can remove USB and connect over the controller's Wi-Fi TCP endpoint." }
            }

            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: connectionDialog.close() }
                PrimaryButton {
                    text: "Connect"
                    enabled: appViewModel && (transportCombo.currentText === "USB serial" ? portCombo.currentText.length > 0 : wifiHostField.text.trim().length > 0)
                    onClicked: {
                        if (transportCombo.currentText === "USB serial") appViewModel.connect_to_usb(portCombo.currentText)
                        else appViewModel.connect_to_wifi(wifiHostField.text, Number(wifiPortField.text))
                        connectionDialog.close()
                    }
                }
            }
        }
    }

    Dialog {
        id: textDialog
        modal: true
        title: "Text engraving"
        width: 650
        height: 700
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        function refreshPreview() {
            if (appViewModel) appViewModel.preview_text(textField.text, fontCombo.currentText, Number(heightField.text), Number(depthField.text), Number(safeField.text), Number(cutField.text), Number(plungeField.text), Number(letterSpacingField.text), Number(lineSpacingField.text), alignmentCombo.currentText, Number(rpmField.text))
        }
        onOpened: refreshPreview()
        onClosed: { if (appViewModel) appViewModel.preview_text("", "Simple", 8, -0.3, 3, 300, 100, 0.18, 1.4, "Left", 0) }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 11
            Label { text: "Create a centerline engraving from the bundled stroke fonts."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: "Text"; color: window.palette.subtle; font.pixelSize: 11 }
            Field { id: textField; Layout.fillWidth: true; text: "TTC 3018"; onTextChanged: textDialog.refreshPreview() }
            GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 8
                Label { text: "Font"; color: window.palette.muted }
                ComboBox { id: fontCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.fonts : ["Simple"]; onActivated: textDialog.refreshPreview() }
                Label { text: "Height (mm)"; color: window.palette.muted }
                Field { id: heightField; Layout.fillWidth: true; text: "8"; validator: DoubleValidator { bottom: 0.5; top: 100 }
                    onTextChanged: textDialog.refreshPreview() }
                Label { text: "Depth (mm)"; color: window.palette.muted }
                Field { id: depthField; Layout.fillWidth: true; text: "-0.3"; validator: DoubleValidator { bottom: -20; top: -0.001 }
                    onTextChanged: textDialog.refreshPreview() }
                Label { text: "Safe Z (mm)"; color: window.palette.muted }
                Field { id: safeField; Layout.fillWidth: true; text: "3"; validator: DoubleValidator { bottom: 0.1; top: 100 }
                    onTextChanged: textDialog.refreshPreview() }
                Label { text: "Cut feed (mm/min)"; color: window.palette.muted }
                Field { id: cutField; Layout.fillWidth: true; text: "300"; validator: DoubleValidator { bottom: 1; top: 3000 }
                    onTextChanged: textDialog.refreshPreview() }
                Label { text: "Plunge feed (mm/min)"; color: window.palette.muted }
                Field { id: plungeField; Layout.fillWidth: true; text: "100"; validator: DoubleValidator { bottom: 1; top: 1000 }
                    onTextChanged: textDialog.refreshPreview() }
                Label { text: "Letter spacing"; color: window.palette.muted }
                Field { id: letterSpacingField; Layout.fillWidth: true; text: "0.18"; validator: DoubleValidator { bottom: 0; top: 2 }
                    onTextChanged: textDialog.refreshPreview() }
                Label { text: "Line spacing"; color: window.palette.muted }
                Field { id: lineSpacingField; Layout.fillWidth: true; text: "1.4"; validator: DoubleValidator { bottom: 1; top: 3 }
                    onTextChanged: textDialog.refreshPreview() }
                Label { text: "Alignment"; color: window.palette.muted }
                ComboBox { id: alignmentCombo; Layout.fillWidth: true; model: ["Left", "Center", "Right"]; onActivated: textDialog.refreshPreview() }
                Label { text: "Spindle RPM (0 = off)"; color: window.palette.muted }
                Field { id: rpmField; Layout.fillWidth: true; text: "0"; validator: IntValidator { bottom: 0; top: 24000 }
                    onTextChanged: textDialog.refreshPreview() }
            }
            Divider {}
            Label { text: appViewModel ? appViewModel.preview_summary : ""; color: window.palette.accent; font.weight: Font.DemiBold; Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: textDialog.close() }
                PrimaryButton { text: "Generate and load"; onClicked: { appViewModel.create_text(textField.text, fontCombo.currentText, Number(heightField.text), Number(depthField.text), Number(safeField.text), Number(cutField.text), Number(plungeField.text), Number(letterSpacingField.text), Number(lineSpacingField.text), alignmentCombo.currentText, Number(rpmField.text)); textDialog.close(); window.workspace = 1 } }
            }
        }
    }

    Dialog {
        id: wifiSetupDialog
        modal: true
        title: "Configure controller Wi-Fi"
        width: 560
        height: 370
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Label { text: "Send station-mode settings to the controller over USB."; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
            Label { text: "The controller will restart after the transaction. Use a 2.4 GHz network; credentials are never saved by this app."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: "Network name (SSID)"; color: window.palette.subtle; font.pixelSize: 11 }
            Field { id: wifiSsidField; Layout.fillWidth: true }
            Label { text: "Wi-Fi password"; color: window.palette.subtle; font.pixelSize: 11 }
            Field { id: wifiPasswordField; Layout.fillWidth: true; echoMode: TextInput.Password }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: wifiSetupDialog.close() }
                PrimaryButton { text: "Configure"; enabled: appViewModel && appViewModel.connected; onClicked: { appViewModel.configure_wifi(wifiSsidField.text, wifiPasswordField.text); wifiPasswordField.text = ""; wifiSetupDialog.close() } }
            }
        }
    }

    Dialog {
        id: profileDialog
        modal: true
        title: "Machine profile"
        width: 480
        height: 470
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 10
            Label { text: "Enter measured usable travel. These values protect the virtual envelope."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: "Machine name"; color: window.palette.subtle; font.pixelSize: 11 }
            Field { id: profileNameField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_name : "Two Trees TTC 3018" }
            GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 8
                Label { text: "X travel (mm)"; color: window.palette.muted }
                Field { id: profileXField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_x.toFixed(2) : "300"; validator: DoubleValidator { bottom: 0.001; top: 1000 } }
                Label { text: "Y travel (mm)"; color: window.palette.muted }
                Field { id: profileYField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_y.toFixed(2) : "180"; validator: DoubleValidator { bottom: 0.001; top: 1000 } }
                Label { text: "Z travel (mm)"; color: window.palette.muted }
                Field { id: profileZField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_z.toFixed(2) : "45"; validator: DoubleValidator { bottom: 0.001; top: 1000 } }
                Label { text: "Safe Z (mm)"; color: window.palette.muted }
                Field { id: profileSafeField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_safe_z.toFixed(2) : "3"; validator: DoubleValidator { bottom: 0; top: 1000 } }
            }
            Label { text: appViewModel ? appViewModel.profile_summary : ""; color: window.palette.subtle; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: profileDialog.close() }
                PrimaryButton { text: "Save profile"; onClicked: { appViewModel.save_profile(profileNameField.text, Number(profileXField.text), Number(profileYField.text), Number(profileZField.text), Number(profileSafeField.text)); profileDialog.close() } }
            }
        }
    }

    Dialog {
        id: consoleDialog
        modal: true
        title: "Controller console"
        width: 820
        height: 520
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 16; spacing: 10
            Label { text: "Read-only transport and GRBL messages"; color: window.palette.muted }
            Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: "#14161A"; radius: 8; border.color: window.palette.divider
                ListView { id: consoleList; anchors.fill: parent; anchors.margins: 10; model: appViewModel ? appViewModel.log_lines : []; clip: true; delegate: Label { width: consoleList.width; text: modelData; color: window.palette.muted; font.family: "Cascadia Mono"; font.pixelSize: 11; wrapMode: Text.NoWrap }
                    onCountChanged: if (count > 0) positionViewAtEnd()
                }
            }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Close"; onClicked: consoleDialog.close() }
            }
        }
    }

    Dialog {
        id: plaqueDialog
        modal: true
        title: "Plaque builder"
        width: 720
        height: 720
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        function refreshPreview() {
            if (appViewModel) appViewModel.preview_plaque(titleField.text, subtitleField.text, subtitleCheck.checked, titleFontCombo.currentText, subtitleFontCombo.currentText, Number(titleHeightField.text), Number(subtitleHeightField.text), Number(widthField.text), Number(plaqueHeightField.text), Number(marginField.text), borderCombo.currentText, Number(plaqueDepthField.text), Number(plaqueSafeField.text), Number(plaqueCutField.text), Number(plaquePlungeField.text), Number(plaqueRpmField.text))
        }
        onOpened: refreshPreview()
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 9
            Label { text: "Build a plaque with protected text margins and a decorative border."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 7
                Label { text: "Title"; color: window.palette.muted }
                Field { id: titleField; Layout.fillWidth: true; text: "Welcome"; onTextChanged: plaqueDialog.refreshPreview() }
                Label { text: "Title font"; color: window.palette.muted }
                ComboBox { id: titleFontCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.fonts : ["Simple"]; onActivated: plaqueDialog.refreshPreview() }
                Label { text: "Title height (mm)"; color: window.palette.muted }
                Field { id: titleHeightField; Layout.fillWidth: true; text: "10"; validator: DoubleValidator { bottom: 0.5; top: 100 }
                    onTextChanged: plaqueDialog.refreshPreview() }
                Label { text: "Subtitle"; color: window.palette.muted }
                Field { id: subtitleField; Layout.fillWidth: true; text: ""; onTextChanged: plaqueDialog.refreshPreview() }
                Label { text: "Enable subtitle"; color: window.palette.muted }
                CheckBox { id: subtitleCheck; checked: true; onCheckedChanged: plaqueDialog.refreshPreview() }
                Label { text: "Subtitle font"; color: window.palette.muted }
                ComboBox { id: subtitleFontCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.fonts : ["Simple"]; onActivated: plaqueDialog.refreshPreview() }
                Label { text: "Subtitle height (mm)"; color: window.palette.muted }
                Field { id: subtitleHeightField; Layout.fillWidth: true; text: "5"; validator: DoubleValidator { bottom: 0.5; top: 100 }
                    onTextChanged: plaqueDialog.refreshPreview() }
                Label { text: "Plaque width × height (mm)"; color: window.palette.muted }
                RowLayout { Layout.fillWidth: true
                    Field { id: widthField; Layout.fillWidth: true; text: "100"; validator: DoubleValidator { bottom: 10; top: 300 }
                        onTextChanged: plaqueDialog.refreshPreview() }
                    Field { id: plaqueHeightField; Layout.fillWidth: true; text: "50"; validator: DoubleValidator { bottom: 10; top: 180 }
                        onTextChanged: plaqueDialog.refreshPreview() }
                }
                Label { text: "Inner margin (mm)"; color: window.palette.muted }
                Field { id: marginField; Layout.fillWidth: true; text: "5"; validator: DoubleValidator { bottom: 1; top: 80 }
                    onTextChanged: plaqueDialog.refreshPreview() }
                Label { text: "Border"; color: window.palette.muted }
                ComboBox { id: borderCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.borders : ["Rectangle"]; onActivated: plaqueDialog.refreshPreview() }
            }
            Divider {}
            GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 7
                Label { text: "Depth / safe Z (mm)"; color: window.palette.muted }
                RowLayout { Layout.fillWidth: true
                    Field { id: plaqueDepthField; Layout.fillWidth: true; text: "-0.3"; onTextChanged: plaqueDialog.refreshPreview() }
                    Field { id: plaqueSafeField; Layout.fillWidth: true; text: "3"; onTextChanged: plaqueDialog.refreshPreview() }
                }
                Label { text: "Cut / plunge feed"; color: window.palette.muted }
                RowLayout { Layout.fillWidth: true
                    Field { id: plaqueCutField; Layout.fillWidth: true; text: "300"; onTextChanged: plaqueDialog.refreshPreview() }
                    Field { id: plaquePlungeField; Layout.fillWidth: true; text: "100"; onTextChanged: plaqueDialog.refreshPreview() }
                }
                Label { text: "Spindle RPM (0 = off)"; color: window.palette.muted }
                Field { id: plaqueRpmField; Layout.fillWidth: true; text: "0"; onTextChanged: plaqueDialog.refreshPreview() }
            }
            Label { text: appViewModel ? appViewModel.preview_summary : ""; color: window.palette.accent; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: plaqueDialog.close() }
                PrimaryButton { text: "Generate and load"; onClicked: { appViewModel.create_plaque(titleField.text, subtitleField.text, subtitleCheck.checked, titleFontCombo.currentText, subtitleFontCombo.currentText, Number(titleHeightField.text), Number(subtitleHeightField.text), Number(widthField.text), Number(plaqueHeightField.text), Number(marginField.text), borderCombo.currentText, Number(plaqueDepthField.text), Number(plaqueSafeField.text), Number(plaqueCutField.text), Number(plaquePlungeField.text), Number(plaqueRpmField.text)); plaqueDialog.close(); window.workspace = 1 } }
            }
        }
    }

    Dialog {
        id: stepDialog
        modal: true
        title: "STEP / 2.5D machining"
        width: 980
        height: 760
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        function refreshPreview() {
            if (appViewModel) appViewModel.preview_step(modeCombo.currentText, orientationCombo.currentText, Number(stockWidthField.text), Number(stockHeightField.text), zeroLocationCombo.currentText, Number(toolDiameterField.text), Number(stepDepthField.text), Number(stepPassesField.text), Number(stepSafeField.text), Number(stepCutField.text), Number(stepPlungeField.text), Number(stepRpmField.text))
        }
        onOpened: refreshPreview()
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 10
            Label { text: "Import a simple planar STEP top face and generate a bounded 2.5D toolpath."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout { Layout.fillWidth: true; spacing: 10
                SecondaryButton { text: "Import STEP…"; onClicked: stepFileDialog.open() }
                Label { text: appViewModel ? appViewModel.step_source : "No STEP model imported"; color: window.palette.text; elide: Text.ElideMiddle; Layout.fillWidth: true }
            }
            Label { text: appViewModel ? appViewModel.step_model_summary : "Import a planar STEP model to begin."; color: window.palette.accent; font.weight: Font.DemiBold; Layout.fillWidth: true }
            RowLayout { Layout.fillWidth: true; spacing: 10
                Label { text: "Machining face"; color: window.palette.muted }
                ComboBox { id: planeCombo; Layout.preferredWidth: 250; model: appViewModel ? appViewModel.step_planes : ["Auto (largest planar face)"]; onActivated: appViewModel.set_step_plane(currentText) }
                Label { text: appViewModel && appViewModel.step_loaded ? "Select a planar face, then use path rotation below if needed." : "Choose a planar face when the CAD model is standing on its side."; color: window.palette.muted; elide: Text.ElideRight; Layout.fillWidth: true }
            }
            RowLayout { Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 12; modeLabel: "STEP PREVIEW" }
                }
                Panel { Layout.preferredWidth: 390; Layout.minimumWidth: 390; Layout.maximumWidth: 390; Layout.fillHeight: true
                    ScrollView { anchors.fill: parent; anchors.margins: 14; clip: true; contentWidth: availableWidth
                        ColumnLayout { width: parent.width; spacing: 8
                            SectionTitle { text: "Model and stock" }
                            Label { text: "Machining mode"; color: window.palette.muted; font.pixelSize: 11 }
                            ComboBox { id: modeCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.step_modes : ["Engraving"]; onActivated: stepDialog.refreshPreview() }
                            Label { text: "Path rotation"; color: window.palette.muted; font.pixelSize: 11 }
                            ComboBox { id: orientationCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.step_orientations : ["Top (XY)"]; onActivated: stepDialog.refreshPreview() }
                            Label { text: "Work zero"; color: window.palette.muted; font.pixelSize: 11 }
                            ComboBox { id: zeroLocationCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.step_zero_locations : ["Center"]; currentIndex: 1; onActivated: stepDialog.refreshPreview() }
                            GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 10; rowSpacing: 7
                                Label { text: "Stock width (mm)"; color: window.palette.muted }
                                Field { id: stockWidthField; Layout.fillWidth: true; text: "50"; validator: DoubleValidator { bottom: 0.1; top: 1000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Stock height (mm)"; color: window.palette.muted }
                                Field { id: stockHeightField; Layout.fillWidth: true; text: "35"; validator: DoubleValidator { bottom: 0.1; top: 1000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Tool diameter (mm)"; color: window.palette.muted }
                                Field { id: toolDiameterField; Layout.fillWidth: true; text: "3.175"; validator: DoubleValidator { bottom: 0.1; top: 20 }
                                    onTextChanged: stepDialog.refreshPreview() }
                            }
                            Divider {}
                            SectionTitle { text: "Cut parameters" }
                            GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 10; rowSpacing: 7
                                Label { text: "Depth (mm)"; color: window.palette.muted }
                                Field { id: stepDepthField; Layout.fillWidth: true; text: "-0.5"; validator: DoubleValidator { bottom: -20; top: -0.001 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Depth passes"; color: window.palette.muted }
                                Field { id: stepPassesField; Layout.fillWidth: true; text: "2"; validator: IntValidator { bottom: 1; top: 100 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Safe Z (mm)"; color: window.palette.muted }
                                Field { id: stepSafeField; Layout.fillWidth: true; text: "3"; validator: DoubleValidator { bottom: 0.1; top: 100 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Cut feed (mm/min)"; color: window.palette.muted }
                                Field { id: stepCutField; Layout.fillWidth: true; text: "300"; validator: DoubleValidator { bottom: 1; top: 3000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Plunge feed (mm/min)"; color: window.palette.muted }
                                Field { id: stepPlungeField; Layout.fillWidth: true; text: "100"; validator: DoubleValidator { bottom: 1; top: 1000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Spindle RPM (0 = off)"; color: window.palette.muted }
                                Field { id: stepRpmField; Layout.fillWidth: true; text: "0"; validator: IntValidator { bottom: 0; top: 24000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                            }
                            MutedLabel { text: "Outside/inside contours apply the tool radius. Pocket uses nested clearing rings. Hole mode requires circular inner loops." }
                        }
                    }
                }
            }
            Label { text: appViewModel ? appViewModel.preview_summary : ""; color: window.palette.accent; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: stepDialog.close() }
                PrimaryButton { text: "Generate and load"; enabled: appViewModel && appViewModel.step_loaded; onClicked: { appViewModel.create_step(modeCombo.currentText, orientationCombo.currentText, Number(stockWidthField.text), Number(stockHeightField.text), zeroLocationCombo.currentText, Number(toolDiameterField.text), Number(stepDepthField.text), Number(stepPassesField.text), Number(stepSafeField.text), Number(stepCutField.text), Number(stepPlungeField.text), Number(stepRpmField.text)); stepDialog.close(); window.workspace = 1 } }
            }
        }
    }

    PlatformDialogs.FileDialog {
        id: stepFileDialog
        title: "Import planar STEP model"
        nameFilters: ["STEP files (*.step *.stp)", "All files (*.*)"]
        onAccepted: {
            appViewModel.import_step_file(selectedFile)
            stepDialog.refreshPreview()
        }
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
        Layout.fillWidth: true
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

    component JogArrowButton: Button {
        id: jogControl
        property string glyph: ""
        property bool fine: false
        padding: 3
        font.pixelSize: fine ? 15 : 13
        font.weight: Font.DemiBold
        contentItem: Text {
            text: jogControl.glyph
            color: jogControl.enabled ? window.palette.text : window.palette.subtle
            font: jogControl.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            lineHeight: 0.9
            lineHeightMode: Text.ProportionalHeight
        }
        background: Rectangle {
            radius: jogControl.fine ? 8 : 12
            color: jogControl.down ? window.palette.accent : jogControl.hovered ? window.palette.hover : jogControl.fine ? "#252A32" : window.palette.raised
            border.width: 1
            border.color: jogControl.down ? window.palette.accentHover : jogControl.enabled ? window.palette.divider : "#30343A"
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
                Pill { label: appViewModel ? appViewModel.connection_text : "Disconnected"; tone: window.palette.warning }
                Pill { label: appViewModel ? appViewModel.grbl_state : "Unknown"; tone: window.palette.muted }
                SecondaryButton { text: appViewModel && appViewModel.connected ? "Disconnect" : "Connect"; onClicked: appViewModel && appViewModel.connected ? appViewModel.disconnect() : connectionDialog.open() }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 48
                spacing: 6

                Repeater {
                    model: ["Prepare", "Preview & Run", "Machine", "Guided Setup"]
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
                Label { text: "TTC 3018 workspace"; color: window.palette.subtle; font.pixelSize: 11 }
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
            StatusMetric { name: "Machine"; value: appViewModel ? appViewModel.machine_position : "X—  Y—  Z—"; tone: window.palette.text }
            StatusMetric { name: "Work"; value: appViewModel ? appViewModel.work_position : "X—  Y—  Z—"; tone: window.palette.text }
            StatusMetric { name: "Reference"; value: appViewModel ? appViewModel.reference : "Position unknown"; tone: window.palette.warning }
            StatusMetric { name: "Work zero"; value: appViewModel ? appViewModel.work_zero : "Not confirmed"; tone: window.palette.warning }
            Item { Layout.fillWidth: true }
            StatusMetric { name: "Spindle"; value: appViewModel ? appViewModel.spindle : "Off"; tone: window.palette.muted }
        }
    }

    StackLayout {
        anchors.fill: parent
        anchors.margins: 18
        currentIndex: window.workspace

        // Prepare
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 210; Layout.minimumWidth: 210; Layout.maximumWidth: 210; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 10
                        SectionTitle { text: "Create or load" }
                        MutedLabel { text: "Start with an existing G-code file or create a centerline engraving." }
                        Divider {}
                        Repeater { model: ["Load G-code", "Text engraving", "Plaque builder", "STEP / 2.5D"]
                            delegate: SecondaryButton {
                                Layout.fillWidth: true
                                text: modelData
                                onClicked: index === 0 ? appViewModel.load_gcode() : index === 1 ? textDialog.open() : index === 2 ? plaqueDialog.open() : stepDialog.open()
                            }
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
                Panel { Layout.preferredWidth: 310; Layout.minimumWidth: 310; Layout.maximumWidth: 310; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 13
                        SectionTitle { text: "Job inspector" }
                        MutedLabel { text: "Select a job source to edit its settings and see the exact centerline toolpath." }
                        Divider {}
                        Label { text: appViewModel ? appViewModel.job_file : "No job selected"; color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true }
                        MutedLabel { text: appViewModel ? appViewModel.job_summary : "Load G-code, create text, or build a plaque. The canvas remains the single source of visual context."; Layout.fillWidth: true }
                        Item { Layout.fillHeight: true }
                        SecondaryButton { Layout.fillWidth: true; text: "Save validated G-code"; enabled: appViewModel && appViewModel.job_file !== "No G-code loaded"; onClicked: appViewModel.save_gcode() }
                        PrimaryButton { Layout.fillWidth: true; text: "Review & run"; onClicked: window.workspace = 1 }
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
                Panel { Layout.preferredWidth: 355; Layout.minimumWidth: 355; Layout.maximumWidth: 355; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 13
                        SectionTitle { text: "Preflight" }
                        Pill { label: appViewModel && appViewModel.job_file !== "No G-code loaded" ? "Validated G-code loaded" : "No validated job loaded"; tone: appViewModel && appViewModel.job_file !== "No G-code loaded" ? window.palette.success : window.palette.warning }
                        Divider {}
                        Label { text: appViewModel && appViewModel.job_active ? appViewModel.job_state + " · " + appViewModel.job_progress + "%" : "Ready when verified"; color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold }
                        ProgressBar { Layout.fillWidth: true; from: 0; to: 100; value: appViewModel ? appViewModel.job_progress : 0; visible: appViewModel && appViewModel.job_file !== "No G-code loaded" }
                        Repeater { model: ["Machine is connected and Idle", "Virtual reference is trusted", "XYZ work zero is confirmed", "Job fits the virtual envelope", "Material and tool are secure"]
                            delegate: RowLayout { Layout.fillWidth: true; spacing: 8
                                property bool passed: index === 0 ? (appViewModel && appViewModel.grbl_state === "Idle") : index === 1 ? (appViewModel && appViewModel.reference_trusted) : index === 2 ? (appViewModel && appViewModel.work_zero_confirmed) : index === 3 ? (appViewModel && appViewModel.job_file !== "No G-code loaded") : true
                                Rectangle { width: 17; height: 17; radius: 8.5; color: parent.passed ? Qt.rgba(window.palette.success.r, window.palette.success.g, window.palette.success.b, 0.18) : "transparent"; border.color: parent.passed ? window.palette.success : window.palette.subtle; border.width: 1; Label { anchors.centerIn: parent; text: parent.parent.passed ? "✓" : ""; color: window.palette.success; font.bold: true } }
                                Label { text: modelData; color: parent.passed ? window.palette.text : window.palette.muted; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            }
                        }
                        Item { Layout.fillHeight: true }
                        PrimaryButton { Layout.fillWidth: true; text: "Start job"; enabled: appViewModel && appViewModel.can_start_job; opacity: enabled ? 1 : 0.55; onClicked: appViewModel.start_job() }
                        RowLayout { Layout.fillWidth: true
                            SecondaryButton { Layout.fillWidth: true; text: "Pause"; enabled: appViewModel && appViewModel.job_active; onClicked: appViewModel.pause_job() }
                            SecondaryButton { Layout.fillWidth: true; text: "Resume"; enabled: appViewModel && appViewModel.job_active; onClicked: appViewModel.resume_job() }
                            SecondaryButton { Layout.fillWidth: true; text: "Abort"; enabled: appViewModel && appViewModel.job_active; onClicked: appViewModel.abort_job() }
                        }
                        Divider {}
                        RowLayout { Layout.fillWidth: true
                            SecondaryButton { Layout.fillWidth: true; text: "Spindle on"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.start_spindle(12000) }
                            SecondaryButton { Layout.fillWidth: true; text: "Spindle off"; enabled: appViewModel && appViewModel.connected; onClicked: appViewModel.stop_spindle() }
                        }
                    }
                }
            }
        }

        // Machine
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 210; Layout.minimumWidth: 210; Layout.maximumWidth: 210; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 8
                        SectionTitle { text: "Machine" }
                        SecondaryButton { Layout.fillWidth: true; text: "Status"; onClicked: window.toastText = appViewModel.grbl_state + " · " + appViewModel.machine_position }
                        SecondaryButton { Layout.fillWidth: true; text: "Connection"; onClicked: connectionDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Configure controller Wi-Fi"; enabled: appViewModel && appViewModel.connected; onClicked: wifiSetupDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Machine profile"; onClicked: profileDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Coordinates"; onClicked: window.toastText = "Machine " + appViewModel.machine_position + " · Work " + appViewModel.work_position }
                        SecondaryButton { Layout.fillWidth: true; text: "Console"; onClicked: consoleDialog.open() }
                        Item { Layout.fillHeight: true }
                        MutedLabel { text: "Reference and work zero are intentionally separate safety states." }
                    }
                }
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 18; modeLabel: "MACHINE"; showEnvelope: true }
                }
                Panel { Layout.preferredWidth: 365; Layout.minimumWidth: 365; Layout.maximumWidth: 365; Layout.fillHeight: true
                    ScrollView { anchors.fill: parent; anchors.margins: 18; clip: true; contentWidth: availableWidth
                    ColumnLayout { width: parent.width; spacing: 12
                        SectionTitle { text: "Position the machine" }
                        MutedLabel { text: "Use small steps near the workpiece. Commands are ignored while GRBL is not Idle and are checked against the trusted envelope." }
                        RowLayout { Layout.fillWidth: true
                            Label { text: "Feed"; color: window.palette.muted; font.pixelSize: 12 }
                            Field { id: jogFeedField; Layout.preferredWidth: 78; text: "500"; validator: DoubleValidator { bottom: 1; top: 1500 } }
                            Label { text: "mm/min"; color: window.palette.subtle; font.pixelSize: 11 }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout { Layout.alignment: Qt.AlignHCenter; spacing: 12
                            Item {
                                id: xyJogPad
                                width: 214
                                height: 214

                                Rectangle { anchors.fill: parent; radius: 18; color: "#1D2025"; border.color: window.palette.divider; border.width: 1 }
                                Label { anchors.centerIn: parent; text: "XY"; color: window.palette.muted; font.pixelSize: 10; font.weight: Font.DemiBold }

                                // Outer ring: press and hold for live jogging; release stops at the nearest whole mm.
                                JogArrowButton { x: 76; y: 6; width: 62; height: 42; glyph: "▲\nY+"; enabled: appViewModel && appViewModel.can_live_jog; onPressed: appViewModel.start_live_jog("Y", 1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { x: 7; y: 86; width: 58; height: 42; glyph: "◀\nX−"; enabled: appViewModel && appViewModel.can_live_jog; onPressed: appViewModel.start_live_jog("X", -1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { x: 149; y: 86; width: 58; height: 42; glyph: "▶\nX+"; enabled: appViewModel && appViewModel.can_live_jog; onPressed: appViewModel.start_live_jog("X", 1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { x: 76; y: 166; width: 62; height: 42; glyph: "▼\nY−"; enabled: appViewModel && appViewModel.can_live_jog; onPressed: appViewModel.start_live_jog("Y", -1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }

                                // Inner ring: one click moves the selected step.
                                JogArrowButton { x: 86; y: 58; width: 42; height: 24; glyph: "▲"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("Y", 0.1) }
                                JogArrowButton { x: 72; y: 91; width: 24; height: 32; glyph: "◀"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("X", -0.1) }
                                JogArrowButton { x: 118; y: 91; width: 24; height: 32; glyph: "▶"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("X", 0.1) }
                                JogArrowButton { x: 86; y: 132; width: 42; height: 24; glyph: "▼"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("Y", -0.1) }
                            }

                            ColumnLayout { Layout.alignment: Qt.AlignVCenter; spacing: 7
                                Label { text: "Z AXIS"; color: window.palette.subtle; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                                JogArrowButton { Layout.preferredWidth: 76; Layout.preferredHeight: 47; glyph: "▲\nZ+"; enabled: appViewModel && appViewModel.can_live_jog; onPressed: appViewModel.start_live_jog("Z", 1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { Layout.preferredWidth: 76; Layout.preferredHeight: 34; glyph: "Z+"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("Z", 0.1) }
                                JogArrowButton { Layout.preferredWidth: 76; Layout.preferredHeight: 34; glyph: "Z−"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("Z", -0.1) }
                                JogArrowButton { Layout.preferredWidth: 76; Layout.preferredHeight: 47; glyph: "▼\nZ−"; enabled: appViewModel && appViewModel.can_live_jog; onPressed: appViewModel.start_live_jog("Z", -1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                            }
                        }
                        Label { Layout.alignment: Qt.AlignHCenter; text: "Inner click: 0.1 mm  ·  Outer hold: live jog, nearest whole-mm stop"; color: window.palette.subtle; font.pixelSize: 10 }
                        SecondaryButton { Layout.alignment: Qt.AlignHCenter; width: 108; text: "Cancel jog"; enabled: appViewModel && appViewModel.connected; onClicked: appViewModel.cancel_jog() }
                        Divider {}
                        SectionTitle { text: "Move to virtual coordinates" }
                        GridLayout { Layout.fillWidth: true; columns: 2
                            Label { text: "X"; color: window.palette.muted }
                            Field { id: targetX; text: "0.00"; Layout.fillWidth: true; validator: DoubleValidator {} }
                            Label { text: "Y"; color: window.palette.muted }
                            Field { id: targetY; text: "0.00"; Layout.fillWidth: true; validator: DoubleValidator {} }
                            Label { text: "Z"; color: window.palette.muted }
                            Field { id: targetZ; text: "0.00"; Layout.fillWidth: true; validator: DoubleValidator {} }
                        }
                        SecondaryButton { Layout.fillWidth: true; text: "Move safely"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.move_to(Number(targetX.text), Number(targetY.text), Number(targetZ.text), Number(jogFeedField.text)) }
                        Divider {}
                        SecondaryButton { Layout.fillWidth: true; text: "Retract to safe Z"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.retract_safe_z() }
                        SecondaryButton { Layout.fillWidth: true; text: "Return to work zero"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.return_to_work_zero() }
                        SecondaryButton { Layout.fillWidth: true; text: "Return to virtual reference"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.return_to_reference() }
                        SecondaryButton { Layout.fillWidth: true; text: "Establish reference here"; enabled: appViewModel && appViewModel.connected && !appViewModel.job_active; onClicked: appViewModel.establish_reference() }
                        GridLayout { Layout.fillWidth: true; columns: 4; columnSpacing: 6
                            SecondaryButton { Layout.fillWidth: true; text: "Zero X"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.set_work_zero("X") }
                            SecondaryButton { Layout.fillWidth: true; text: "Zero Y"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.set_work_zero("Y") }
                            SecondaryButton { Layout.fillWidth: true; text: "Zero Z"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.set_work_zero("Z") }
                            PrimaryButton { Layout.fillWidth: true; text: "Zero XYZ"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.set_work_zero("XYZ") }
                        }
                    }
                    }
                }
            }
        }

        // Guided setup
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 265; Layout.minimumWidth: 265; Layout.maximumWidth: 265; Layout.fillHeight: true
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
                        RowLayout { Layout.fillWidth: true
                            Item { Layout.fillWidth: true }
                            SecondaryButton { text: "Open machine controls"; onClicked: window.workspace = 2 }
                            PrimaryButton { text: "Continue to connection"; onClicked: connectionDialog.open() }
                        }
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
                if ((showJob || modeLabel === "PREPARE") && (!appViewModel || appViewModel.preview_strokes.length === 0)) {
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
                if (appViewModel && appViewModel.preview_strokes.length > 0) {
                    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
                    for (const stroke of appViewModel.preview_strokes) for (const point of stroke) {
                        minX = Math.min(minX, point[0]); minY = Math.min(minY, point[1]); maxX = Math.max(maxX, point[0]); maxY = Math.max(maxY, point[1])
                    }
                    const spanX = Math.max(0.001, maxX - minX), spanY = Math.max(0.001, maxY - minY)
                    const scale = Math.min((width - 2 * inset) / spanX, (height - 2 * inset) / spanY)
                    const offsetX = (width - spanX * scale) / 2 - minX * scale
                    const offsetY = height - inset + minY * scale
                    ctx.strokeStyle = "#168BFF"; ctx.lineWidth = 2.2; ctx.lineCap = "round"; ctx.lineJoin = "round"
                    for (const stroke of appViewModel.preview_strokes) {
                        if (!stroke.length) continue
                        ctx.beginPath(); ctx.moveTo(offsetX + stroke[0][0] * scale, offsetY - stroke[0][1] * scale)
                        for (let index = 1; index < stroke.length; index++) ctx.lineTo(offsetX + stroke[index][0] * scale, offsetY - stroke[index][1] * scale)
                        ctx.stroke()
                    }
                }
                ctx.fillStyle = "#40C4D9"
                ctx.beginPath(); ctx.arc(inset, height - inset, 6, 0, Math.PI * 2); ctx.fill()
            }
        }
        Connections { target: appViewModel; function onState_changed() { canvas.requestPaint() } }
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
