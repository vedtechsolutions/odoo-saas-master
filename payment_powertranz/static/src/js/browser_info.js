/** @odoo-module **/

/**
 * Utility class to collect browser information required for 3DS authentication.
 */
export class BrowserInfoCollector {
    static getBrowserInfo() {
        let javaEnabled = false;
        try {
            javaEnabled = navigator.javaEnabled();
        } catch (e) {
            // Accessing navigator.javaEnabled() can throw errors in some environments
            console.warn("Could not determine if Java is enabled: ", e);
        }
        return {
            language: navigator.language || navigator.userLanguage || navigator.browserLanguage || 'en-US',
            screenHeight: window.screen.height.toString(),
            screenWidth: window.screen.width.toString(),
            timeZone: new Date().getTimezoneOffset().toString(), // Timezone offset in minutes
            userAgent: navigator.userAgent,
            colorDepth: window.screen.colorDepth.toString(),
            javaEnabled: javaEnabled,
            javascriptEnabled: true, // If this code runs, JS is enabled
        };
    }

    /**
     * Asynchronously sends browser info to the backend to be enriched with server-side data (IP).
     * 
     * @param {string} browserInfoUrl The backend URL to fetch enriched browser info.
     * @param {object} rpcService The RPC service for making backend calls.
     * @returns {Promise<object>} A promise that resolves with the enriched browser info.
     */
    static async getEnrichedBrowserInfo(browserInfoUrl, rpcService) {
        const clientInfo = this.getBrowserInfo();
        try {
            // Call the backend controller endpoint
            const enrichedInfo = await rpcService(browserInfoUrl, clientInfo);
            if (enrichedInfo.error) {
                console.error("Error fetching enriched browser info:", enrichedInfo.error);
                // Fallback to client-side info + default IP?
                return { ...clientInfo, ip: '0.0.0.0' }; 
            }
            return enrichedInfo;
        } catch (error) {
            console.error("RPC error fetching enriched browser info:", error);
            // Fallback to client-side info + default IP?
            return { ...clientInfo, ip: '0.0.0.0' }; 
        }
    }
} 