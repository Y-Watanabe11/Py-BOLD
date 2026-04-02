      *----------------------------------------------------------------
      * CUSTOMER-CALC
      * Classic "Py-BOL" specimen: cryptic WS- names, procedural
      * flow, arithmetic + conditional in a single paragraph.
      * This is the snippet used to validate the Py-BOLD AST tracer.
      *----------------------------------------------------------------
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTOMER-CALC.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CUST-ID-X         PIC 9(6)    VALUE 0.
       01 WS-ORDER-AMT-N       PIC 9(7)V99 VALUE 0.
       01 WS-DISCOUNT-RT-N     PIC 9(3)V99 VALUE 0.
       01 WS-DISCOUNT-AMT-N    PIC 9(7)V99 VALUE 0.
       01 WS-FINAL-AMT-N       PIC 9(7)V99 VALUE 0.
       01 WS-PREMIUM-FLAG-X    PIC X       VALUE 'N'.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 100423         TO WS-CUST-ID-X.
           MOVE 1500.00        TO WS-ORDER-AMT-N.
           IF WS-ORDER-AMT-N > 1000
               MOVE 'Y'        TO WS-PREMIUM-FLAG-X
               COMPUTE WS-DISCOUNT-RT-N = 15
           ELSE
               COMPUTE WS-DISCOUNT-RT-N = 5
           END-IF.
           COMPUTE WS-DISCOUNT-AMT-N =
               WS-ORDER-AMT-N * WS-DISCOUNT-RT-N / 100.
           COMPUTE WS-FINAL-AMT-N =
               WS-ORDER-AMT-N - WS-DISCOUNT-AMT-N.
           DISPLAY 'CUSTOMER: ' WS-CUST-ID-X.
           DISPLAY 'FINAL AMOUNT: ' WS-FINAL-AMT-N.
           STOP RUN.
