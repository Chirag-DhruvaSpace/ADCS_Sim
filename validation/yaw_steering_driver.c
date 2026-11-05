/* Test access to the actual firmware; this file is never added to sitl_ads.exe. */
#include "cmd_handler.h"
#include "Guidance/yaw_steering/yaw_steering.h"
#include "control/yaw_steering/yaw_steering_control.h"
#include "control/state_machine.h"
#include "control/control_laws.h"
#include "command/acs.h"
#include "utils/utils.h"
#include "utils/fdir.h"
#include <math.h>
#include <string.h>

extern void resetDefaults(void);
extern volatile uint8_t gpsFusionPositionUsable;

void yaw_test_init(void)
{
    resetDefaults();
    stateMachine_Init();
    AdsHk.AdcsMode = AdcsMode_YawSteering;
    memset(&fdirErrCnters, 0, sizeof(fdirErrCnters));
    for (int i=0; i<4; i++) cmdActValues.RwTorque[i]=RW_ZERO_TORQUE;
    desatVars.desatFlag=0;
}

void yaw_test_step(double *r, double *v, double *q, double *w, double *out)
{
    memcpy(&AdsMdl.PosVectorECI, r, 3*sizeof(double));
    memcpy(&AdsMdl.VelVectorECI, v, 3*sizeof(double));
    memcpy(&AdsMdl.fusedquat, q, 4*sizeof(double));
    memcpy(&AdsMdl.bodyRate, w, 3*sizeof(double));
    AdsMdl.Wmag=utilsMod(AdsMdl.bodyRate);
    calcYawSteeringFrame();
    calculate_yaw_steering_torque();
    out[0]=yawSteeringVars.yawDeg;
    memcpy(out+1, &yawSteeringVars.qTarget, 4*sizeof(double));
    memcpy(out+5, &yawSteeringVars.omegaFf, 3*sizeof(double));
    memcpy(out+8, &yawSteeringVars.controlTorque, 3*sizeof(double));
    out[11]=yawSteeringVars.valid;
    actuate_yaw_steering_torque();
    for (int i=0; i<4; i++)
        out[12+i]=((double)cmdActValues.RwTorque[i]-RW_TORQUE_CONV_OFFSET)/RW_TORQUE_CONV_SLOPE;
}

int yaw_test_mode(int request, int gps, int wheels)
{
    gpsFusionPositionUsable=gps;
    for (int i=0; i<4; i++) smVars.health.rw[i]=wheels;
    /* Enter from the same standalone state used by the existing modes. */
    smVars.state=State_NominalInOrbit;
    triggerEvent(Event_RequestYawSteering);
    stateMachine_Update();
    if (request == 1) triggerEvent(Event_ExitStandaloneMode);
    if (request == 2) triggerEvent(Event_EnterNadirPointing);
    if (request) stateMachine_Update();
    return AdsHk.AdcsMode;
}

int yaw_test_event_number(void) { return Event_RequestYawSteering; }

static CommsContext testComms;

int yaw_test_command_open(void)
{
    struct sockaddr_in address;
    int length = sizeof(address);
    if (Comms_Init(&testComms, 0)) return -1;
    getsockname(testComms.listen_sock, (struct sockaddr *)&address, &length);
    return ntohs(address.sin_port);
}

int yaw_test_command_accept(void) { return Comms_WaitForClient(&testComms); }

int yaw_test_command_poll(void)
{
    gpsFusionPositionUsable=1;
    for (int i=0; i<4; i++) smVars.health.rw[i]=1;
    CmdHandler_Poll(&testComms);
    stateMachine_Update();
    return AdsHk.AdcsMode;
}

void yaw_test_command_close(void) { Comms_Cleanup(&testComms); }
