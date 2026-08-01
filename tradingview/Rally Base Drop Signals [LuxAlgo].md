// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=6
indicator("Rally Base Drop Signals [LuxAlgo]", "LuxAlgo - RBD Signals", overlay = true)
//---------------------------------------------------------------------------------------------------------------------}
//Inputs
//---------------------------------------------------------------------------------------------------------------------{
rbdTog = input.bool(true, title = "Rally | Base | Drop", group = "Sequences")
rbrTog = input.bool(true, title = "Rally | Base | Rally", group = "Sequences")
dbdTog = input.bool(true, title = "Drop | Base | Drop", group = "Sequences")
dbrTog = input.bool(true, title = "Drop | Base | Rally", group = "Sequences")


bcType = input.string("Full Color", title = "Bar Color Logic", options = ["Full Color", "Color on Detection", "No Color"], group = "Style", tooltip = "Full Color: Colors the full 'Rally' or 'Drop' candles, coloring the first bar of the pattern historically.\n\nColor on Detection: Only Colors the literal bars detecting the patterns. Will not historically color the first bar of the 'Rally' or 'Drop'.\n\nNo Color: Disables Bar Coloring.")

rallyCol = input.color(#089981c0, title = "Rally Color", group = "Style")
baseCol = input.color(#00000000,title = "Base Color", group = "Style")
dropCol = input.color(#f23645c0,title = "Drop Color", group = "Style")
txtCol = input.color(color.gray, title = "Label Color", group = "Style")
labSize = str.lower(input.string("Small",title = "Label Size", options = ["Tiny","Small","Normal","Large","Huge"], group = "Style"))

//---------------------------------------------------------------------------------------------------------------------}
//Calcs
//---------------------------------------------------------------------------------------------------------------------{
gc = close > open
rc = close < open

rally = gc and gc[1]
drop = rc and rc[1]
base = not rally and not drop

var o = array.new_string(3,"")

if base and o.last() != "B"
    o.shift()
    o.push("B")
if rally and o.last() != "R"
    o.shift()
    o.push("R")
if drop and o.last() != "D"
    o.shift()
    o.push("D")

readout = str.replace_all(str.tostring(o),", ","")

RBD = readout == "[RBD]" and readout[1] != "[RBD]" and rbdTog
RBR = readout == "[RBR]" and readout[1] != "[RBR]" and rbrTog
DBD = readout == "[DBD]" and readout[1] != "[DBD]" and dbdTog
DBR = readout == "[DBR]" and readout[1] != "[DBR]" and dbrTog

//---------------------------------------------------------------------------------------------------------------------}
//Displays
//---------------------------------------------------------------------------------------------------------------------{
barColor = switch bcType
    "Full Color" => rally ? rallyCol : drop ? dropCol : base ? baseCol : na
    "Color on Detection" => RBR or DBR ? rallyCol : DBD or RBD ? dropCol : na
    => na

barcolor(barColor, title = 'Bar Color')

plotshape(RBD, text = "RBD", style = shape.triangledown, color = dropCol, textcolor = txtCol, display = display.pane)
plotshape(RBR, text = "RBR", style = shape.triangleup, location = location.belowbar, color = rallyCol, textcolor = txtCol, display = display.pane)
plotshape(DBD, text = "DBD", style = shape.triangledown, color = dropCol, textcolor = txtCol, display = display.pane)
plotshape(DBR, text = "DBR", style = shape.triangleup, location = location.belowbar, color = rallyCol, textcolor = txtCol, display = display.pane)

//---------------------------------------------------------------------------------------------------------------------}