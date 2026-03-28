using System.ComponentModel.DataAnnotations;

namespace WebApp.Models
{
    public class Camera
    {
        public int Id { get; set; }

        [Required]
        public string Name { get; set; }

        [Required]
        public string Location { get; set; }

        public string IpAddress { get; set; }

        public int Port { get; set; }
    }
}