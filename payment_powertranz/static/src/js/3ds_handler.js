/** @odoo-module **/

/**
 * Handles the 3D Secure authentication steps (fingerprinting, challenge).
 */
export class PowerTranz3DSHandler {

    /**
     * Executes the device fingerprinting step.
     * 
     * @param {object} fingerprintData Data containing HTML/JS for fingerprinting.
     * @param {string} authenticateUrl The URL to call after fingerprinting.
     * @param {string} spiToken The SPI token for the transaction.
     * @param {string} reference The transaction reference.
     * @param {object} rpcService The RPC service for making backend calls.
     * @returns {Promise<object>} A promise that resolves with the result of the authenticate call.
     */
    static async handleFingerprint(fingerprintData, authenticateUrl, spiToken, reference, rpcService) {
        console.log("PowerTranz: Starting device fingerprinting...");
        return new Promise(async (resolve, reject) => {
            try {
                // Create a hidden iframe for fingerprinting
                const iframe = document.createElement('iframe');
                iframe.style.display = 'none';
                iframe.id = 'powertranz-fingerprint-iframe';
                document.body.appendChild(iframe);

                // Set a timeout for the fingerprinting process
                const timeoutId = setTimeout(() => {
                    console.warn("PowerTranz: Fingerprinting timed out.");
                    this._cleanupFingerprint(iframe.id);
                    reject('Device fingerprinting timed out.');
                }, 15000); // 15 seconds timeout

                // The fingerprintData likely contains HTML that might include a form
                // which posts to the bank's fingerprinting endpoint.
                // We need to inject this into the iframe.
                iframe.contentWindow.document.open();
                iframe.contentWindow.document.write(fingerprintData);
                iframe.contentWindow.document.close();

                // How do we know fingerprinting is done? The PowerTranz docs should specify.
                // Option A: The injected script might post a message back.
                // Option B: We might just have to wait a fixed time or assume it completes quickly.
                // Option C: The injected content might redirect the iframe, triggering onload.
                
                // Assuming Option B/C for simplicity here: Wait briefly, then proceed.
                // A robust solution needs specific details from PowerTranz.
                
                // Simulate waiting or listen for iframe load/message if applicable.
                // For now, wait a short period then call authenticate.
                await new Promise(r => setTimeout(r, 5000)); // Wait 5 seconds (adjust based on testing)
                
                clearTimeout(timeoutId);
                console.log("PowerTranz: Fingerprinting presumed complete. Proceeding to Authenticate.");
                this._cleanupFingerprint(iframe.id);

                // Call the backend to continue authentication
                const authResult = await rpcService(authenticateUrl, { spi_token: spiToken, reference: reference });
                resolve(authResult);

            } catch (error) {
                console.error("PowerTranz: Error during fingerprinting handling:", error);
                this._cleanupFingerprint('powertranz-fingerprint-iframe'); // Ensure cleanup
                reject(error);
            }
        });
    }

    /**
     * Handles the 3DS challenge step by redirecting to the challenge page.
     * 
     * @param {string} challengeUrl The Odoo controller URL that renders the challenge page.
     */
    static handleChallenge(challengeUrl) {
        console.log("PowerTranz: Redirecting to 3DS challenge page:", challengeUrl);
        // Redirect the main window to the Odoo page hosting the iframe
        window.location.href = challengeUrl;
        // Alternatively, could open in a modal/popup if the Odoo page is designed for it.
    }

    /**
     * Cleans up fingerprinting iframe.
     * @param {string} iframeId The ID of the iframe to remove.
     */
    static _cleanupFingerprint(iframeId) {
        const iframe = document.getElementById(iframeId);
        if (iframe) {
            document.body.removeChild(iframe);
            console.log("PowerTranz: Cleaned up fingerprint iframe.");
        }
    }
} 