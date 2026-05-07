import time
from machine import I2C


class BME280:
    def __init__(self, i2c, address=0x76):
        self.i2c = i2c
        self.address = address
        self._load_calibration()
        # Sensor in Normal Mode setzen
        self.i2c.writeto_mem(self.address, 0xF4, b'\x27')
        self.i2c.writeto_mem(self.address, 0xF5, b'\xa0')

    def _load_calibration(self):
        d = self.i2c.readfrom_mem(self.address, 0x88, 24)
        self.dig_T1 = (d[1] << 8) | d[0]
        self.dig_T2 = self._to_signed(d[3], d[2])
        self.dig_T3 = self._to_signed(d[5], d[4])
        self.dig_P1 = (d[7] << 8) | d[6]
        self.dig_P2 = self._to_signed(d[9], d[8])
        self.dig_P3 = self._to_signed(d[11], d[10])
        self.dig_P4 = self._to_signed(d[13], d[12])
        self.dig_P5 = self._to_signed(d[15], d[14])
        self.dig_P6 = self._to_signed(d[17], d[16])
        self.dig_P7 = self._to_signed(d[19], d[18])
        self.dig_P8 = self._to_signed(d[21], d[20])
        self.dig_P9 = self._to_signed(d[23], d[22])

        d = self.i2c.readfrom_mem(self.address, 0xA1, 1)
        self.dig_H1 = d[0]
        d = self.i2c.readfrom_mem(self.address, 0xE1, 7)
        self.dig_H2 = self._to_signed(d[1], d[0])
        self.dig_H3 = d[2]
        self.dig_H4 = (d[3] << 4) | (d[4] & 0x0F)
        self.dig_H5 = (d[5] << 4) | (d[4] >> 4)
        self.dig_H6 = self._to_signed(0, d[6])

    def _to_signed(self, high, low):
        val = (high << 8) | low
        if val > 32767:
            val -= 65536
        return val

    def read_values(self):
        data = self.i2c.readfrom_mem(self.address, 0xF7, 8)
        pres_raw = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        temp_raw = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
        hum_raw = (data[6] << 8) | data[7]

        # Temperatur-Kompensation
        var1 = (((temp_raw >> 3) - (self.dig_T1 << 1)) * self.dig_T2) >> 11
        var2 = (((((temp_raw >> 4) - self.dig_T1) *
                ((temp_raw >> 4) - self.dig_T1)) >> 12) * self.dig_T3) >> 14
        t_fine = var1 + var2
        temp = (t_fine * 5 + 128) >> 8

        # Feuchtigkeits-Kompensation
        v_x1 = t_fine - 76800
        v_x1 = (((((hum_raw << 14) - (self.dig_H4 << 20) - (self.dig_H5 * v_x1)) + 16384) >> 15) *
                (((((((v_x1 * self.dig_H6) >> 10) * (((v_x1 * self.dig_H3) >> 11) + 32768)) >> 10) + 2097152) *
                  self.dig_H2 + 8192) >> 14))
        v_x1 = v_x1 - \
            (((((v_x1 >> 15) * (v_x1 >> 15)) >> 7) * self.dig_H1) >> 4)
        v_x1 = 0 if v_x1 < 0 else v_x1
        v_x1 = 419430400 if v_x1 > 419430400 else v_x1
        hum = v_x1 >> 12

        # Luftdruck-Kompensation
        var1 = t_fine - 128000
        var2 = var1 * var1 * self.dig_P6
        var2 = var2 + ((var1 * self.dig_P5) << 17)
        var2 = var2 + (self.dig_P4 << 35)
        var1 = ((var1 * var1 * self.dig_P3) >> 8) + \
            ((var1 * self.dig_P2) << 12)
        var1 = (((1 << 47) + var1) * self.dig_P1) >> 33
        if var1 == 0:
            pres = 0
        else:
            p = 1048576 - pres_raw
            p = (((p << 31) - var2) * 3125) // var1
            var1 = (self.dig_P9 * (p >> 13) * (p >> 13)) >> 25
            var2 = (self.dig_P8 * p) >> 19
            pres = ((p + var1 + var2) >> 8) + (self.dig_P7 << 4)

        return temp / 100.0, pres / 256.0 / 100.0, hum / 1024.0
