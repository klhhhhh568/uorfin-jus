module rotor() {
    // Параметры ротора
    outer_diameter = 40;
    width = 20;
    inner_diameter = 12;
    slot_count = 8;
    slot_depth = 4;
    shaft_diameter = 8;
    
    // Основной цилиндр ротора
    difference() {
        cylinder(h = width, d = outer_diameter, $fn = 64);
        
        // Центральный валик
        cylinder(h = width + 2, d = shaft_diameter, $fn = 32);
        
        // Пазы для магнитов
        for(i = [0 : 360/slot_count : 360-360/slot_count]) {
            rotate([0, 0, i])
            linear_extrude(height = width)
            difference() {
                square([outer_diameter/2 - inner_diameter/2 - slot_depth, width]);
                square([outer_diameter/2 - inner_diameter/2 - slot_depth + 1, width - 2]);
            }
        }
    }
}

rotor();