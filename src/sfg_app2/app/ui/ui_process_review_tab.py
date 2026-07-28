# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'process_review_tab.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton,
    QRadioButton, QSizePolicy, QSpacerItem, QSplitter,
    QVBoxLayout, QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(867, 580)
        self.verticalLayout_2 = QVBoxLayout(Form)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.calibrationFrame = QFrame(Form)
        self.calibrationFrame.setObjectName(u"calibrationFrame")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.calibrationFrame.sizePolicy().hasHeightForWidth())
        self.calibrationFrame.setSizePolicy(sizePolicy)
        self.calibrationFrame.setFrameShape(QFrame.StyledPanel)
        self.calibrationFrame.setFrameShadow(QFrame.Raised)
        self.horizontalLayout = QHBoxLayout(self.calibrationFrame)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.label = QLabel(self.calibrationFrame)
        self.label.setObjectName(u"label")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy1)
        self.label.setMaximumSize(QSize(16777215, 16777215))

        self.horizontalLayout.addWidget(self.label)

        self.upconversionSpinBox = QDoubleSpinBox(self.calibrationFrame)
        self.upconversionSpinBox.setObjectName(u"upconversionSpinBox")
        self.upconversionSpinBox.setDecimals(2)
        self.upconversionSpinBox.setMinimum(400.000000000000000)
        self.upconversionSpinBox.setMaximum(1400.000000000000000)
        self.upconversionSpinBox.setSingleStep(2.000000000000000)
        self.upconversionSpinBox.setValue(1030.700000000000045)

        self.horizontalLayout.addWidget(self.upconversionSpinBox)

        self.calibrateButton = QPushButton(self.calibrationFrame)
        self.calibrateButton.setObjectName(u"calibrateButton")

        self.horizontalLayout.addWidget(self.calibrateButton)

        self.horizontalSpacer = QSpacerItem(40, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)


        self.verticalLayout_2.addWidget(self.calibrationFrame)

        self.splitter = QSplitter(Form)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.leftPanelWidget = QWidget(self.splitter)
        self.leftPanelWidget.setObjectName(u"leftPanelWidget")
        self.verticalLayout = QVBoxLayout(self.leftPanelWidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.reviewReferencesButton = QPushButton(self.leftPanelWidget)
        self.reviewReferencesButton.setObjectName(u"reviewReferencesButton")

        self.verticalLayout.addWidget(self.reviewReferencesButton)

        self.label_2 = QLabel(self.leftPanelWidget)
        self.label_2.setObjectName(u"label_2")
        font = QFont()
        font.setBold(True)
        self.label_2.setFont(font)

        self.verticalLayout.addWidget(self.label_2)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.label_3 = QLabel(self.leftPanelWidget)
        self.label_3.setObjectName(u"label_3")

        self.horizontalLayout_3.addWidget(self.label_3)

        self.singleViewRadio = QRadioButton(self.leftPanelWidget)
        self.singleViewRadio.setObjectName(u"singleViewRadio")
        self.singleViewRadio.setChecked(True)

        self.horizontalLayout_3.addWidget(self.singleViewRadio)

        self.compareViewRadio = QRadioButton(self.leftPanelWidget)
        self.compareViewRadio.setObjectName(u"compareViewRadio")

        self.horizontalLayout_3.addWidget(self.compareViewRadio)


        self.verticalLayout.addLayout(self.horizontalLayout_3)

        self.matchedSetsListWidget = QListWidget(self.leftPanelWidget)
        self.matchedSetsListWidget.setObjectName(u"matchedSetsListWidget")

        self.verticalLayout.addWidget(self.matchedSetsListWidget)

        self.setStatusLabel = QLabel(self.leftPanelWidget)
        self.setStatusLabel.setObjectName(u"setStatusLabel")
        self.setStatusLabel.setWordWrap(True)

        self.verticalLayout.addWidget(self.setStatusLabel)

        self.splitter.addWidget(self.leftPanelWidget)
        self.rightPanelWidget = QWidget(self.splitter)
        self.rightPanelWidget.setObjectName(u"rightPanelWidget")
        self.splitter.addWidget(self.rightPanelWidget)

        self.verticalLayout_2.addWidget(self.splitter)


        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.label.setText(QCoreApplication.translate("Form", u"Up-conversion wavelength:", None))
        self.upconversionSpinBox.setSuffix(QCoreApplication.translate("Form", u" nm", None))
        self.calibrateButton.setText(QCoreApplication.translate("Form", u"\u25b6 Calibrate with polystyrene...", None))
        self.reviewReferencesButton.setText(QCoreApplication.translate("Form", u"Review references", None))
        self.label_2.setText(QCoreApplication.translate("Form", u"Matched Sets", None))
        self.label_3.setText(QCoreApplication.translate("Form", u"View:", None))
        self.singleViewRadio.setText(QCoreApplication.translate("Form", u"Single", None))
        self.compareViewRadio.setText(QCoreApplication.translate("Form", u"Compare", None))
        self.setStatusLabel.setText("")
    # retranslateUi

