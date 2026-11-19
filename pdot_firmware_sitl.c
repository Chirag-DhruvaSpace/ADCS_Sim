/* Host peripheral boundary for the P-Dot OBC detumble task.
 * The Python loader appends the selected unmodified flight routines.
 */
#include <math.h>
#include <stdint.h>
#include <string.h>

typedef struct { double vec[3]; } Vector3;
static struct { double Ixm, Ixp, Iym, Izp; } inputVariable;
static struct {
    double Ixm, Ixp, Iym, Izp, tempo;
    double Magx, Magy, Magz, gyroX, gyroY, gyroZ, icmTemperature;
    double angMomx, angMomy, angMomz;
} outputVariable;
static simpleKalmanStruct kalmanVars;
static const int icmfound = 1, magfound = 1;
static const double gyroSensitivity = 32768.0 / 250.0;
static double MagField[3];
static double bdot_gain[3] = {BDOT_KX, BDOT_KY, BDOT_KZ};
static int magTimePrev = 1;
static Vector3 MagBodyPrev;
static uint32_t simulation_milliseconds;
static const uint8_t *gyroscope_registers, *magnetometer_registers;

static uint32_t osKernelGetTickCount(void) { return simulation_milliseconds; }
static void HAL_Delay(uint32_t milliseconds) { (void)milliseconds; }
static void INA220_PollData(void) {}
static void ICM20948_WriteI2C(uint8_t reg, uint8_t *buffer, uint8_t size)
{ (void)reg; (void)buffer; (void)size; }
static void ICM20948_ReadI2C(uint8_t reg, uint8_t *buffer, uint8_t size)
{ (void)reg; memcpy(buffer, gyroscope_registers, size); }
static void AK09916_ReadI2C(uint8_t reg, uint8_t *buffer, uint8_t size)
{ (void)reg; memcpy(buffer, magnetometer_registers, size); }
static void torquerCoils(Vector3 calculatedMoment);
void computeBDot(void);
void initKalman(float errMeasure, float errEstimate, float procNoise);
void updateEst(double x, double y, double z);
void ICM20948_readGyroAndTempData(void);

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

EXPORT void pdot_initialize(void)
{
    memset(&kalmanVars, 0, sizeof(kalmanVars));
    memset(&inputVariable, 0, sizeof(inputVariable));
    memset(&outputVariable, 0, sizeof(outputVariable));
    magTimePrev = 1;
    initKalman(2, 20, 0.5);
}

EXPORT void pdot_detumble_sample(uint32_t milliseconds, const uint8_t *gyro,
                                 const uint8_t *magnetometer, double *currents)
{
    simulation_milliseconds = milliseconds;
    gyroscope_registers = gyro;
    magnetometer_registers = magnetometer;
    computeBDot();
    /* Signed electrical currents in harness order: X-, X+, Y-, Z+. */
    currents[0] = -inputVariable.Ixm;
    currents[1] = inputVariable.Ixp;
    currents[2] = -inputVariable.Iym;
    currents[3] = inputVariable.Izp;
}
